#!/usr/bin/env python3
"""Read-only inventory scanner for a Gmail Takeout MBOX file.

This script does not extract attachments, modify the MBOX, contact Gmail, or
send content to an LLM.  It streams through the mailbox once and writes a JSON
report plus a human-readable text summary.

Python 3.9+; standard library only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple


VERSION = "1.0.0"
DEFAULT_BATCH_CHARS = 24_000
DEFAULT_SECONDS_PER_REQUEST = 12.0
DEFAULT_MAX_MESSAGE_MIB = 128
ERROR_SAMPLE_LIMIT = 25

MESSAGE_ID_RE = re.compile(r"<[^<>\r\n]+>")
SAFE_STEM_RE = re.compile(r"[^A-Za-z0-9._-]+")

LIKELY_REVIEW_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docm",
    ".docx",
    ".html",
    ".htm",
    ".json",
    ".mqxliff",
    ".ods",
    ".pdf",
    ".rpx",
    ".rtf",
    ".sdlppx",
    ".sdlproj",
    ".sdlrpx",
    ".sdlxliff",
    ".tmx",
    ".tsv",
    ".ttx",
    ".txt",
    ".xls",
    ".xlsb",
    ".xlsm",
    ".xlsx",
    ".xlf",
    ".xliff",
    ".xml",
    ".zip",
}

SYSTEM_GMAIL_LABELS = {
    "all mail",
    "archive",
    "category forums",
    "category personal",
    "category promotions",
    "category social",
    "category updates",
    "chat",
    "draft",
    "important",
    "inbox",
    "opened",
    "sent",
    "spam",
    "starred",
    "trash",
    "unread",
}


def format_bytes(value: int) -> str:
    size = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:,.2f} {unit}"
        size /= 1024.0
    return f"{value:,} B"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def clean_exception(exc: BaseException) -> str:
    # Exception messages from malformed mail can reproduce private header data.
    # The class is sufficient for aggregate diagnostics and is safe to share.
    return type(exc).__name__


class VisibleHTML(HTMLParser):
    """Small, dependency-free HTML-to-visible-text counter."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() in {"script", "style", "head", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "head", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


class DisjointSet:
    """Tracks RFC reply/reference components without retaining message content."""

    def __init__(self) -> None:
        self.parent: Dict[str, str] = {}
        self.rank: Dict[str, int] = {}

    def add(self, item: str) -> None:
        if item not in self.parent:
            self.parent[item] = item
            self.rank[item] = 0

    def find(self, item: str) -> str:
        self.add(item)
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != item:
            parent = self.parent[item]
            self.parent[item] = root
            item = parent
        return root

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left == root_right:
            return
        if self.rank[root_left] < self.rank[root_right]:
            root_left, root_right = root_right, root_left
        self.parent[root_right] = root_left
        if self.rank[root_left] == self.rank[root_right]:
            self.rank[root_left] += 1


def message_ids(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [match.group(0).lower() for match in MESSAGE_ID_RE.finditer(str(value))]


def filename_extension(filename: Optional[str]) -> str:
    if not filename:
        return "[none]"
    name = str(filename).strip().lower()
    match = re.search(r"(\.[a-z0-9]{1,12})$", name)
    return match.group(1) if match else "[none]"


def parse_gmail_labels(values: Iterable[str]) -> List[str]:
    labels: List[str] = []
    for value in values:
        try:
            rows = list(csv.reader([str(value)], skipinitialspace=True))
            labels.extend(item.strip() for item in rows[0] if item.strip())
        except (csv.Error, IndexError):
            labels.extend(item.strip() for item in str(value).split(",") if item.strip())
    return labels


def payload_bytes(part) -> Optional[bytes]:
    decoded = part.get_payload(decode=True)
    if isinstance(decoded, bytes):
        return decoded
    if part.get_content_type() == "message/rfc822":
        payload = part.get_payload()
        if isinstance(payload, list):
            return b"\n".join(item.as_bytes(policy=policy.default) for item in payload)
    if isinstance(decoded, str):
        return decoded.encode("utf-8", errors="replace")
    return None


def decode_text_part(part) -> str:
    try:
        content = part.get_content()
        if isinstance(content, str):
            return content
        if isinstance(content, bytes):
            return content.decode(part.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        pass

    raw = part.get_payload(decode=True)
    if not isinstance(raw, bytes):
        raw_payload = part.get_payload()
        return raw_payload if isinstance(raw_payload, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def visible_body(msg) -> Tuple[str, str]:
    """Return one preferred body representation, avoiding plain/HTML duplication."""
    chosen = None
    try:
        chosen = msg.get_body(preferencelist=("plain", "html"))
    except Exception:
        chosen = None

    if chosen is None:
        candidates = []
        for part in msg.walk():
            if part.is_multipart():
                continue
            disposition = (part.get_content_disposition() or "").lower()
            if disposition == "attachment" or part.get_filename():
                continue
            if part.get_content_type() in {"text/plain", "text/html"}:
                candidates.append(part)
        chosen = next((part for part in candidates if part.get_content_type() == "text/plain"), None)
        if chosen is None and candidates:
            chosen = candidates[0]

    if chosen is None:
        return "", "none"

    text = decode_text_part(chosen)
    kind = "html" if chosen.get_content_type() == "text/html" else "plain"
    if kind == "html" and text:
        parser = VisibleHTML()
        try:
            parser.feed(text)
            parser.close()
            text = parser.text()
        except Exception:
            text = " ".join(text.split())
    return text, kind


def iter_mbox_messages(
    path: Path, max_message_bytes: int
) -> Iterator[Tuple[int, int, int, Optional[bytes]]]:
    """Yield (index, start offset, raw size, content).

    Content is None when a message exceeds the configured in-memory safety cap.
    The source file is opened strictly in binary read mode.
    """
    with path.open("rb") as stream:
        current = bytearray()
        message_index = 0
        message_start = 0
        message_size = 0
        oversized = False
        found_envelope = False
        offset = 0

        while True:
            line = stream.readline()
            if not line:
                break
            line_start = offset
            offset += len(line)

            if line.startswith(b"From "):
                if found_envelope:
                    message_index += 1
                    yield (
                        message_index,
                        message_start,
                        message_size,
                        None if oversized else bytes(current),
                    )
                found_envelope = True
                message_start = line_start
                message_size = 0
                oversized = False
                current = bytearray()
                continue

            if not found_envelope:
                continue

            message_size += len(line)
            if not oversized:
                if message_size <= max_message_bytes:
                    current.extend(line)
                else:
                    oversized = True
                    current = bytearray()

        if found_envelope:
            message_index += 1
            yield (
                message_index,
                message_start,
                message_size,
                None if oversized else bytes(current),
            )


def new_stats(source: Path, source_size: int, args: argparse.Namespace) -> Dict[str, object]:
    modified = datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc)
    return {
        "report": {
            "script": "gmail_mbox_inventory.py",
            "script_version": VERSION,
            "scan_status": "running",
            "scan_started_utc": iso_utc(utc_now()),
            "scan_finished_utc": None,
            "elapsed_seconds": 0.0,
        },
        "source": {
            "filename": source.name,
            "size_bytes": source_size,
            "modified_utc": iso_utc(modified),
            "opened_read_only": True,
        },
        "coverage": {
            "bytes_scanned": 0,
            "percent_scanned": 0.0,
            "messages_seen": 0,
            "messages_parsed": 0,
            "messages_with_parser_defects": 0,
            "parser_defects_by_type": Counter(),
            "messages_failed": 0,
            "messages_over_safety_limit": 0,
            "maximum_message_bytes_seen": 0,
            "error_samples": [],
        },
        "mail": {
            "earliest_date_utc": None,
            "latest_date_utc": None,
            "messages_without_date": 0,
            "messages_with_invalid_date": 0,
            "_gmail_labels_internal": Counter(),
            "gmail_system_labels": Counter(),
            "custom_label_instances": 0,
            "distinct_custom_labels": 0,
            "messages_with_gmail_labels": 0,
            "messages_with_message_id": 0,
            "duplicate_message_ids": 0,
            "messages_with_reply_or_reference_headers": 0,
            "rfc_linked_conversations_approx": 0,
        },
        "text": {
            "messages_with_readable_body": 0,
            "preferred_plain_bodies": 0,
            "preferred_html_bodies": 0,
            "visible_body_characters": 0,
            "visible_body_utf8_bytes": 0,
            "estimated_input_tokens_low": 0,
            "estimated_input_tokens_high": 0,
        },
        "attachments": {
            "instances": 0,
            "decoded_bytes": 0,
            "unique_instances_by_sha256": 0,
            "duplicate_instances_by_sha256": 0,
            "duplicate_decoded_bytes": 0,
            "without_filename": 0,
            "payload_decode_failures": 0,
            "likely_review_file_instances": 0,
            "likely_review_file_bytes": 0,
            "by_extension": Counter(),
            "by_mime_type": Counter(),
        },
        "ollama_planning": {
            "assumed_batch_characters": args.batch_chars,
            "assumed_seconds_per_request": args.seconds_per_request,
            "estimated_discovery_requests": 0,
            "estimated_discovery_hours": 0.0,
            "scope_note": (
                "Planning estimate for email-body discovery only. It includes a small "
                "per-message framing allowance, but excludes attachment extraction, "
                "detailed feedback extraction, retries, and model warm-up."
            ),
        },
        "notes": [
            "Conversation count is approximate and is based on RFC Message-ID, References, and In-Reply-To links.",
            "Attachment hashes are counted for deduplication; hashes and attachment contents are not written to the report.",
            "No message bodies, subjects, addresses, filenames, or attachment contents are written to the report.",
            "Custom Gmail label names are redacted unless --include-label-names is explicitly used.",
        ],
    }


def add_error(stats: Dict[str, object], stage: str, index: int, offset: int, exc: BaseException) -> None:
    samples: List[Dict[str, object]] = stats["coverage"]["error_samples"]  # type: ignore[index]
    if len(samples) < ERROR_SAMPLE_LIMIT:
        samples.append(
            {
                "stage": stage,
                "message_index": index,
                "source_offset_bytes": offset,
                "error": clean_exception(exc),
            }
        )


def process_message(
    raw: bytes,
    index: int,
    offset: int,
    stats: Dict[str, object],
    threads: DisjointSet,
    message_nodes: Set[str],
    seen_message_ids: Set[str],
    attachment_hashes: Set[str],
) -> None:
    coverage = stats["coverage"]  # type: ignore[assignment]
    mail = stats["mail"]  # type: ignore[assignment]
    text_stats = stats["text"]  # type: ignore[assignment]
    attachments = stats["attachments"]  # type: ignore[assignment]

    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        coverage["messages_parsed"] += 1
    except Exception as exc:
        coverage["messages_failed"] += 1
        add_error(stats, "message_parse", index, offset, exc)
        return

    defects = list(getattr(msg, "defects", []) or [])
    if defects:
        coverage["messages_with_parser_defects"] += 1
        for defect in defects:
            coverage["parser_defects_by_type"][type(defect).__name__] += 1

    date_header = msg.get("Date")
    if date_header is None:
        mail["messages_without_date"] += 1
    else:
        try:
            parsed = parsedate_to_datetime(str(date_header))
            if parsed is None:
                raise ValueError("Date header could not be parsed")
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            parsed = parsed.astimezone(timezone.utc)
            current_min = mail["earliest_date_utc"]
            current_max = mail["latest_date_utc"]
            parsed_iso = iso_utc(parsed)
            if current_min is None or parsed_iso < current_min:
                mail["earliest_date_utc"] = parsed_iso
            if current_max is None or parsed_iso > current_max:
                mail["latest_date_utc"] = parsed_iso
        except Exception as exc:
            mail["messages_with_invalid_date"] += 1
            add_error(stats, "date_parse", index, offset, exc)

    try:
        labels = parse_gmail_labels(msg.get_all("X-Gmail-Labels", []))
        if labels:
            mail["messages_with_gmail_labels"] += 1
            mail["_gmail_labels_internal"].update(labels)
    except Exception as exc:
        add_error(stats, "gmail_labels", index, offset, exc)

    ids = message_ids(str(msg.get("Message-ID") or ""))
    node = f"anon:{index}"
    if ids:
        message_id = ids[0]
        mail["messages_with_message_id"] += 1
        if message_id in seen_message_ids:
            mail["duplicate_message_ids"] += 1
            node = f"duplicate:{index}:{message_id}"
            threads.union(node, message_id)
        else:
            node = message_id
            seen_message_ids.add(message_id)
    threads.add(node)
    message_nodes.add(node)

    refs = message_ids(str(msg.get("References") or ""))
    reply_ids = message_ids(str(msg.get("In-Reply-To") or ""))
    linked_ids = refs + reply_ids
    if linked_ids:
        mail["messages_with_reply_or_reference_headers"] += 1
        for linked_id in linked_ids:
            threads.union(node, linked_id)

    try:
        body, body_kind = visible_body(msg)
        if body:
            text_stats["messages_with_readable_body"] += 1
            text_stats["visible_body_characters"] += len(body)
            text_stats["visible_body_utf8_bytes"] += len(body.encode("utf-8", errors="replace"))
            if body_kind == "plain":
                text_stats["preferred_plain_bodies"] += 1
            elif body_kind == "html":
                text_stats["preferred_html_bodies"] += 1
    except Exception as exc:
        add_error(stats, "body_decode", index, offset, exc)

    for part in msg.walk():
        try:
            disposition = (part.get_content_disposition() or "").lower()
            filename = part.get_filename()
            content_type = part.get_content_type().lower()
            is_attachment = bool(filename) or disposition == "attachment"
            if disposition == "inline" and content_type not in {"text/plain", "text/html"}:
                is_attachment = True
            if not is_attachment:
                continue

            attachments["instances"] += 1
            extension = filename_extension(filename)
            attachments["by_extension"][extension] += 1
            attachments["by_mime_type"][content_type] += 1
            if not filename:
                attachments["without_filename"] += 1

            data = payload_bytes(part)
            if data is None:
                attachments["payload_decode_failures"] += 1
                continue
            size = len(data)
            attachments["decoded_bytes"] += size
            digest = hashlib.sha256(data).hexdigest()
            if digest in attachment_hashes:
                attachments["duplicate_instances_by_sha256"] += 1
                attachments["duplicate_decoded_bytes"] += size
            else:
                attachment_hashes.add(digest)

            if extension in LIKELY_REVIEW_EXTENSIONS:
                attachments["likely_review_file_instances"] += 1
                attachments["likely_review_file_bytes"] += size
        except Exception as exc:
            attachments["payload_decode_failures"] += 1
            add_error(stats, "attachment_inventory", index, offset, exc)


def finalise_stats(
    stats: Dict[str, object],
    source_size: int,
    started_monotonic: float,
    threads: DisjointSet,
    message_nodes: Set[str],
    attachment_hashes: Set[str],
    scan_status: str,
) -> None:
    coverage = stats["coverage"]  # type: ignore[assignment]
    mail = stats["mail"]  # type: ignore[assignment]
    text_stats = stats["text"]  # type: ignore[assignment]
    attachments = stats["attachments"]  # type: ignore[assignment]
    planning = stats["ollama_planning"]  # type: ignore[assignment]
    report = stats["report"]  # type: ignore[assignment]

    scanned = int(coverage["bytes_scanned"])
    coverage["percent_scanned"] = round((100.0 * scanned / source_size) if source_size else 100.0, 3)
    mail["rfc_linked_conversations_approx"] = len({threads.find(node) for node in message_nodes})
    attachments["unique_instances_by_sha256"] = len(attachment_hashes)

    all_labels = mail.pop("_gmail_labels_internal")
    system_labels = Counter()
    custom_labels = Counter()
    for label, count in all_labels.items():
        if label.casefold() in SYSTEM_GMAIL_LABELS:
            system_labels[label] += count
        else:
            custom_labels[label] += count
    mail["gmail_system_labels"] = system_labels
    mail["custom_label_instances"] = sum(custom_labels.values())
    mail["distinct_custom_labels"] = len(custom_labels)
    if bool(stats["report"].get("include_custom_label_names")):
        mail["gmail_labels_by_name"] = all_labels

    chars = int(text_stats["visible_body_characters"])
    text_stats["estimated_input_tokens_low"] = math.ceil(chars / 4.0)
    text_stats["estimated_input_tokens_high"] = math.ceil(chars / 3.0)
    framing_chars = int(coverage["messages_parsed"]) * 220
    effective_chars = chars + framing_chars
    requests = math.ceil(effective_chars / int(planning["assumed_batch_characters"])) if effective_chars else 0
    planning["estimated_discovery_requests"] = requests
    planning["estimated_discovery_hours"] = round(
        requests * float(planning["assumed_seconds_per_request"]) / 3600.0, 2
    )

    report["scan_status"] = scan_status
    report["scan_finished_utc"] = iso_utc(utc_now())
    report["elapsed_seconds"] = round(time.monotonic() - started_monotonic, 2)


def json_ready(value):
    if isinstance(value, Counter):
        return {key: value[key] for key in sorted(value, key=lambda item: (-value[item], item))}
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value


def top_counter_lines(counter: Dict[str, int], limit: int = 30) -> List[str]:
    if not counter:
        return ["  (none)"]
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
    lines = [f"  {name}: {count:,}" for name, count in items]
    remaining = len(counter) - len(items)
    if remaining:
        lines.append(f"  ... plus {remaining:,} more values in the JSON report")
    return lines


def text_report(stats: Dict[str, object]) -> str:
    report = stats["report"]
    source = stats["source"]
    coverage = stats["coverage"]
    mail = stats["mail"]
    text_stats = stats["text"]
    attachments = stats["attachments"]
    planning = stats["ollama_planning"]

    lines = [
        "Gmail MBOX inventory",
        "====================",
        "",
        f"Status: {report['scan_status']}",
        f"Source: {source['filename']}",
        f"Source size: {format_bytes(source['size_bytes'])} ({source['size_bytes']:,} bytes)",
        f"Scanned: {coverage['percent_scanned']:.3f}%",
        f"Elapsed: {report['elapsed_seconds']:,.2f} seconds",
        "",
        "Coverage",
        "--------",
        f"Messages seen: {coverage['messages_seen']:,}",
        f"Messages parsed: {coverage['messages_parsed']:,}",
        f"Messages with parser defects: {coverage['messages_with_parser_defects']:,}",
        f"Messages that failed parsing: {coverage['messages_failed']:,}",
        f"Messages over safety limit: {coverage['messages_over_safety_limit']:,}",
        f"Largest message: {format_bytes(coverage['maximum_message_bytes_seen'])}",
        "",
        "Mailbox",
        "-------",
        f"Date range: {mail['earliest_date_utc'] or '[unknown]'} to {mail['latest_date_utc'] or '[unknown]'}",
        f"Messages without a usable date: {mail['messages_without_date'] + mail['messages_with_invalid_date']:,}",
        f"Approximate RFC-linked conversations: {mail['rfc_linked_conversations_approx']:,}",
        f"Messages carrying Gmail labels: {mail['messages_with_gmail_labels']:,}",
        f"Distinct custom Gmail labels: {mail['distinct_custom_labels']:,}",
        f"Custom-label instances: {mail['custom_label_instances']:,}",
        "",
        "Readable email text",
        "-------------------",
        f"Messages with a readable preferred body: {text_stats['messages_with_readable_body']:,}",
        f"Visible body characters: {text_stats['visible_body_characters']:,}",
        f"Visible body UTF-8 size: {format_bytes(text_stats['visible_body_utf8_bytes'])}",
        f"Approximate input tokens: {text_stats['estimated_input_tokens_low']:,} to {text_stats['estimated_input_tokens_high']:,}",
        "",
        "Attachments",
        "-----------",
        f"Attachment instances: {attachments['instances']:,}",
        f"Decoded attachment size: {format_bytes(attachments['decoded_bytes'])}",
        f"Unique attachments by SHA-256: {attachments['unique_instances_by_sha256']:,}",
        f"Duplicate attachment instances: {attachments['duplicate_instances_by_sha256']:,}",
        f"Likely review/document instances: {attachments['likely_review_file_instances']:,}",
        f"Likely review/document size: {format_bytes(attachments['likely_review_file_bytes'])}",
        f"Attachment payload decode failures: {attachments['payload_decode_failures']:,}",
        "",
        "Ollama discovery planning estimate",
        "----------------------------------",
        f"Assumed batch size: {planning['assumed_batch_characters']:,} characters",
        f"Estimated requests: {planning['estimated_discovery_requests']:,}",
        f"At {planning['assumed_seconds_per_request']:g} seconds/request: about {planning['estimated_discovery_hours']:,.2f} hours",
        f"Note: {planning['scope_note']}",
        "",
        "System Gmail labels",
        "-------------------",
    ]
    lines.extend(top_counter_lines(mail["gmail_system_labels"]))
    if "gmail_labels_by_name" in mail:
        lines.extend(["", "All Gmail labels (explicitly included)", "-------------------------------------"])
        lines.extend(top_counter_lines(mail["gmail_labels_by_name"]))
    lines.extend(["", "Attachment extensions", "---------------------"])
    lines.extend(top_counter_lines(attachments["by_extension"]))
    lines.extend(["", "Attachment MIME types", "---------------------"])
    lines.extend(top_counter_lines(attachments["by_mime_type"]))

    if coverage["error_samples"]:
        lines.extend(["", "Error samples", "-------------"])
        for sample in coverage["error_samples"]:
            lines.append(
                f"  message {sample['message_index']:,}, offset {sample['source_offset_bytes']:,}, "
                f"{sample['stage']}: {sample['error']}"
            )

    lines.extend(
        [
            "",
            "Privacy",
            "-------",
            "This report contains aggregate counts only. It does not contain message bodies,",
            "subjects, addresses, attachment filenames, attachment hashes, attachment contents,",
            "or custom Gmail label names (unless explicitly requested).",
            "",
        ]
    )
    return "\n".join(lines)


def unique_output_paths(output_dir: Path, source: Path) -> Tuple[Path, Path]:
    safe_stem = SAFE_STEM_RE.sub("_", source.stem).strip("._-")[:40] or "mailbox"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = output_dir / f"{safe_stem}-inventory-{stamp}"
    suffix = 1
    while base.with_suffix(".json").exists() or base.with_suffix(".txt").exists():
        base = output_dir / f"{safe_stem}-inventory-{stamp}-{suffix}"
        suffix += 1
    return base.with_suffix(".json"), base.with_suffix(".txt")


def write_reports(stats: Dict[str, object], json_path: Path, text_path: Path) -> None:
    ready = json_ready(stats)
    json_path.write_text(json.dumps(ready, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text_path.write_text(text_report(ready), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a read-only, aggregate inventory of a Gmail Takeout MBOX file."
    )
    parser.add_argument("mbox", type=Path, help="Path to the .mbox file")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory for the JSON and text reports (default: current directory)",
    )
    parser.add_argument(
        "--progress-seconds",
        type=float,
        default=15.0,
        help="Seconds between console progress updates (default: 15)",
    )
    parser.add_argument(
        "--max-message-mib",
        type=int,
        default=DEFAULT_MAX_MESSAGE_MIB,
        help=f"Per-message parsing safety limit in MiB (default: {DEFAULT_MAX_MESSAGE_MIB})",
    )
    parser.add_argument(
        "--batch-chars",
        type=int,
        default=DEFAULT_BATCH_CHARS,
        help=f"Characters per future Ollama discovery batch (default: {DEFAULT_BATCH_CHARS})",
    )
    parser.add_argument(
        "--seconds-per-request",
        type=float,
        default=DEFAULT_SECONDS_PER_REQUEST,
        help=f"Runtime assumption for future planning (default: {DEFAULT_SECONDS_PER_REQUEST:g})",
    )
    parser.add_argument(
        "--include-label-names",
        action="store_true",
        help="Include custom Gmail label names in reports (off by default for privacy)",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.mbox.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()

    if not source.is_file():
        print(f"Error: MBOX file not found: {source}", file=sys.stderr)
        return 2
    if args.max_message_mib < 1 or args.batch_chars < 1 or args.seconds_per_request <= 0:
        print("Error: numeric options must be positive.", file=sys.stderr)
        return 2
    output_dir.mkdir(parents=True, exist_ok=True)

    source_size = source.stat().st_size
    json_path, text_path = unique_output_paths(output_dir, source)
    stats = new_stats(source, source_size, args)
    stats["report"]["include_custom_label_names"] = bool(args.include_label_names)
    threads = DisjointSet()
    message_nodes: Set[str] = set()
    seen_message_ids: Set[str] = set()
    attachment_hashes: Set[str] = set()
    started = time.monotonic()
    next_progress = started
    max_message_bytes = args.max_message_mib * 1024 * 1024
    scan_status = "complete"

    print(f"Scanning read-only: {source.name} ({format_bytes(source_size)})")
    print("No message content will be written to the reports. Press Ctrl+C for a partial report.")

    try:
        for index, offset, raw_size, raw in iter_mbox_messages(source, max_message_bytes):
            coverage = stats["coverage"]
            coverage["messages_seen"] = index
            coverage["bytes_scanned"] = min(source_size, offset + raw_size)
            coverage["maximum_message_bytes_seen"] = max(
                int(coverage["maximum_message_bytes_seen"]), raw_size
            )

            if raw is None:
                coverage["messages_over_safety_limit"] += 1
            else:
                process_message(
                    raw,
                    index,
                    offset,
                    stats,
                    threads,
                    message_nodes,
                    seen_message_ids,
                    attachment_hashes,
                )

            now = time.monotonic()
            if now >= next_progress:
                percent = 100.0 * int(coverage["bytes_scanned"]) / source_size if source_size else 100.0
                elapsed = max(now - started, 0.001)
                rate_mib = int(coverage["bytes_scanned"]) / elapsed / (1024 * 1024)
                print(
                    f"  {percent:6.2f}% | {index:,} messages | {rate_mib:,.1f} MiB/s | "
                    f"{coverage['messages_failed']:,} parse failures",
                    flush=True,
                )
                next_progress = now + args.progress_seconds
    except KeyboardInterrupt:
        scan_status = "interrupted_partial"
        print("\nInterrupted; writing a partial report...", file=sys.stderr)
    except Exception as exc:
        scan_status = "failed_partial"
        add_error(
            stats,
            "mailbox_scan",
            int(stats["coverage"]["messages_seen"]),
            int(stats["coverage"]["bytes_scanned"]),
            exc,
        )
        print(f"\nScan error; writing a partial report: {clean_exception(exc)}", file=sys.stderr)

    if scan_status == "complete":
        stats["coverage"]["bytes_scanned"] = source_size
    finalise_stats(
        stats,
        source_size,
        started,
        threads,
        message_nodes,
        attachment_hashes,
        scan_status,
    )
    write_reports(stats, json_path, text_path)

    print(f"Text report: {text_path}")
    print(f"JSON report: {json_path}")
    if scan_status == "complete":
        print("Inventory complete.")
        return 0
    return 130 if scan_status == "interrupted_partial" else 1


if __name__ == "__main__":
    raise SystemExit(main())
