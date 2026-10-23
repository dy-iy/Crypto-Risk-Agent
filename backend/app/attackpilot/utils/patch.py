import re
from difflib import SequenceMatcher
from typing import Dict, Tuple, List


def build_applied_patch_record(original: Dict[str, str], updated: Dict[str, str]) -> str:
    """Render only source changes that were actually applied, independently of prose."""
    records = []
    for file_id in sorted(original):
        before, after = original[file_id], updated.get(file_id)
        if not isinstance(before, str) or not isinstance(after, str):
            continue
        old_lines, new_lines = before.splitlines(), after.splitlines()
        if old_lines == new_lines:
            continue
        blocks = []
        for group in SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_grouped_opcodes(8):
            first, last = group[0], group[-1]
            old = "\n".join(old_lines[first[1]:last[2]])
            new = "\n".join(new_lines[first[3]:last[4]])
            blocks.append(f"<<<<<<< SEARCH\n{old}\n=======\n{new}\n>>>>>>> REPLACE")
        records.append(f"# File: {file_id}\n" + "\n\n".join(blocks))
    return "\n\n".join(records)


class SolidityCodePatcher:
    def __init__(self, sources_map: Dict[str, str]):
        self.sources = {k: v.splitlines() for k, v in sources_map.items()}
        self.modified_sources = {key: list(lines) for key, lines in self.sources.items()}

    def apply_patches(self, llm_response: str) -> Tuple[bool, str, Dict[str, str]]:
        self.modified_sources = {key: list(lines) for key, lines in self.sources.items()}
        llm_response = llm_response.replace('\r\n', '\n')

        file_blocks = self._split_by_file(llm_response)
        if not file_blocks:
            return False, "Error: No file blocks found (missing '# File: ...').", {}

        logs = []
        overall_success = True

        for file_id, blocks in file_blocks.items():
            if file_id not in self.modified_sources:
                logs.append(f"Warning: File '{file_id}' not found in source map. Skipping.")
                overall_success = False
                continue

            for block_index, content_block in enumerate(blocks):
                success, log = self._apply_single_block(file_id, content_block)
                status = "SUCCESS" if success else "ERROR"
                logs.append(f"[{status}] File: {file_id} (Block {block_index + 1}) | {log}")

                if not success:
                    overall_success = False

        if not overall_success:
            self.modified_sources = {key: list(lines) for key, lines in self.sources.items()}
        final_sources = {k: "\n".join(lines) for k, lines in self.modified_sources.items()}
        return overall_success, "\n".join(logs), final_sources

    def _split_by_file(self, text: str) -> Dict[str, List[str]]:
        pattern = re.compile(r'^#\s*File:\s*(.+?)\s*$', re.MULTILINE)
        matches = list(pattern.finditer(text))
        result: Dict[str, List[str]] = {}

        if not matches:
            return {}

        for i, match in enumerate(matches):
            file_id = match.group(1).strip()
            start_idx = match.end()
            end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start_idx:end_idx]

            if file_id not in result:
                result[file_id] = []
            result[file_id].append(content)
        return result

    def _apply_single_block(self, file_id: str, patch_text: str) -> Tuple[bool, str]:
        current_lines = self.modified_sources[file_id]

        # Normalize the block delimiters without changing source tokens.
        pattern = re.compile(
            r'<<<<<<< SEARCH\s*\n(.*?)\n=======\s*\n(.*?)\n>>>>>>> REPLACE',
            re.DOTALL
        )
        matches = pattern.findall(patch_text)

        marker_count = len(re.findall(r"^(?:<<<<<<< SEARCH|=======|>>>>>>> REPLACE)[ \t]*$", patch_text, re.MULTILINE))
        if not matches or marker_count != 3 * len(matches):
            return False, "Missing or malformed SEARCH/REPLACE block."

        applied_count = 0

        for search_block, replace_block in matches:
            search_lines = search_block.splitlines()
            replace_lines = replace_block.splitlines()

            match_start, match_end, status = self._robust_find_index(current_lines, search_lines)

            if status == -1:
                trimmed_search_lines = self._trim_empty_lines(search_lines)
                if len(trimmed_search_lines) < len(search_lines):
                    m_start2, m_end2, status2 = self._robust_find_index(current_lines, trimmed_search_lines)
                    if status2 == 0:
                        search_lines = trimmed_search_lines
                        match_start, match_end, status = m_start2, m_end2, status2

            if status == -1:
                return False, (
                    "SEARCH block does not match the source exactly (apart from indentation).\n"
                    f"Context:\n{search_block}"
                )
            if status == -2:
                return False, (
                    "SEARCH block is ambiguous (multiple source occurrences)."
                )

            target_indent = self._get_indent_string(current_lines[match_start])
            final_replace_lines = self._reindent_block(replace_lines, target_indent)

            end_index_exclusive = match_end + 1
            current_lines[match_start: end_index_exclusive] = final_replace_lines
            applied_count += 1

        self.modified_sources[file_id] = current_lines
        return True, f"Applied {applied_count} patches successfully."

    def _robust_find_index(
            self,
            source_lines: List[str],
            search_lines: List[str]
    ) -> Tuple[int, int, int]:
        if not search_lines:
            return -1, -1, -1

        # Only indentation may differ. Removing comments or whitespace inside
        # literals can target a different expression ("a b" != "ab").
        normalized_search = [line.strip() for line in search_lines]
        spans = [index for index in range(len(source_lines) - len(search_lines) + 1)
                 if [line.strip() for line in source_lines[index:index + len(search_lines)]] == normalized_search]
        if len(spans) == 1:
            return spans[0], spans[0] + len(search_lines) - 1, 0
        return -1, -1, -2 if spans else -1

    def _reindent_block(self, lines: List[str], target_indent: str) -> List[str]:
        if not lines:
            return []

        non_empty_lines = [l for l in lines if l.strip()]
        if not non_empty_lines:
            return lines

        indents = [len(l) - len(l.lstrip()) for l in non_empty_lines]
        min_indent_len = min(indents)

        reindented_lines: List[str] = []
        for line in lines:
            if not line.strip():
                reindented_lines.append("")
                continue
            content = line[min_indent_len:]

            reindented_lines.append(target_indent + content)

        return reindented_lines

    def _get_indent_string(self, line: str) -> str:
        return line[:len(line) - len(line.lstrip())]

    def _trim_empty_lines(self, lines: List[str]) -> List[str]:
        start = 0
        while start < len(lines) and not lines[start].strip():
            start += 1

        end = len(lines)
        while end > start and not lines[end - 1].strip():
            end -= 1

        return lines[start:end]
