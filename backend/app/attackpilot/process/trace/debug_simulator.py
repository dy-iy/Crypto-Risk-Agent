from typing import Dict

from app.attackpilot.entities.trace import TraceNode
from app.attackpilot.settings import INIT_DEPTH


class DebugSimulator:
    def __init__(self, root_node: TraceNode, node_map: Dict[int, TraceNode]):
        self.root_node = root_node
        self.node_map = node_map

        if self.root_node:
            self._init_view_state(self.root_node)
            self.expand_trace_by_depth(INIT_DEPTH)

    def _init_view_state(self, node):
        if not hasattr(node, 'view_expanded'):
            node.view_expanded = False

        for child in node.children:
            self._init_view_state(child)

    def render(self):
        if not self.root_node:
            return "Empty Trace"

        lines = []

        def _recursive_render(node, prefix, is_last):
            if node == self.root_node:
                connector = ""
                new_prefix = ""
            else:
                connector = "└── " if is_last else "├── "
                child_prefix_segment = "    " if is_last else "│   "
                new_prefix = prefix + child_prefix_segment

            info = node.format_node()
            lines.append(f"{prefix}{connector}{info}")

            if not node.children:
                return

            if getattr(node, 'view_expanded', False):
                count = len(node.children)
                for i, child in enumerate(node.children):
                    is_last_child = (i == count - 1)
                    _recursive_render(child, new_prefix, is_last_child)
            else:
                collapse_info = f"... ({len(node.children)} sub-calls collapsed)"
                lines.append(f"{new_prefix}└── {collapse_info}")

        _recursive_render(self.root_node, "", True)
        return "\n".join(lines)

    def expand_trace_by_depth(self, depth):
        for node in self.node_map.values():
            if node.depth < depth:
                node.view_expanded = True
            else:
                node.view_expanded = False

    def expand_node(self, node_index, n=1):
        node = self.node_map.get(node_index)
        if not node:
            raise ValueError(f"Node {node_index} not found.")
        if type(n) is not int or n < 0:
            raise ValueError("Expansion depth must be a nonnegative integer.")

        def _recursive_expand(_node):
            if _node.depth > max_depth:
                return
            _node.view_expanded = True
            if not _node.children:
                return
            for child in _node.children:
                if self.judge_node_with_role(child):
                    _recursive_expand(child)

        max_depth = node.depth + n
        _recursive_expand(node)

    def collapse_node(self, node_index):
        node = self.node_map.get(node_index)
        if not node:
            raise ValueError(f"Node {node_index} not found.")
        node.view_expanded = False

    def judge_node_with_role(self, node):
        if node.address_to and self._is_precompile(node.address_to):
            return False
        if node.trace_type == 'STATICCALL' and (node.gas_used or 0) < 2000:
            return False
        return True

    def _is_precompile(self, address):
        try:
            val = int(address, 16)
            return 1 <= val <= 9
        except Exception:
            return False

    def update_comments(self, comments: Dict[str, str]):
        updates = []
        for index_str, comment_text in comments.items():
            try:
                node_index = int(index_str)
            except (ValueError, TypeError):
                raise ValueError("Comment indexes must identify existing trace nodes.") from None
            node = self.node_map.get(node_index)
            if node is None or not isinstance(comment_text, str):
                raise ValueError("Comments require an existing node and a string value.")
            updates.append((node, comment_text))
        for node, comment_text in updates:
            node.comment = comment_text
