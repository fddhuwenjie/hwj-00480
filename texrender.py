#!/usr/bin/env python3
"""LaTeX数学公式到终端ASCII Art渲染的CLI工具"""

import sys
import re
import math
import difflib
import argparse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Callable


# =====================================================================
# 盒模型 (Box Model)
# =====================================================================

@dataclass
class Box:
    """表示一个渲染好的ASCII Art矩形区域"""
    lines: List[str]
    width: int
    height: int
    baseline: int  # 基线所在行（从顶部0开始计数）

    @classmethod
    def from_lines(cls, lines: List[str], baseline: int = 0) -> 'Box':
        width = max((len(line) for line in lines), default=0)
        padded = [line.ljust(width) for line in lines]
        return cls(lines=padded, width=width, height=len(padded), baseline=baseline)

    @classmethod
    def from_string(cls, text: str) -> 'Box':
        lines = text.split('\n')
        return cls.from_lines(lines, baseline=len(lines) // 2 if len(lines) > 1 else 0)


def box_hconcat(boxes: List[Box], baseline_align: bool = True) -> Box:
    """水平拼接多个Box，按基线对齐"""
    if not boxes:
        return Box.from_lines([""])
    if len(boxes) == 1:
        return boxes[0]

    if baseline_align:
        max_above = max(b.baseline for b in boxes)
        max_below = max(b.height - 1 - b.baseline for b in boxes)
        total_height = max_above + max_below + 1
    else:
        total_height = max(b.height for b in boxes)
        max_above = total_height - 1

    result_lines = []
    for i in range(total_height):
        line_parts = []
        for b in boxes:
            if baseline_align:
                src_row = i - (max_above - b.baseline)
            else:
                src_row = i
            if 0 <= src_row < b.height:
                line_parts.append(b.lines[src_row])
            else:
                line_parts.append(' ' * b.width)
        result_lines.append(''.join(line_parts))

    return Box.from_lines(result_lines, baseline=max_above if baseline_align else 0)


def box_vconcat(top_box: Box, bottom_box: Box, center: bool = True) -> Box:
    """垂直拼接两个Box"""
    if center:
        width = max(top_box.width, bottom_box.width)
        top_lines = [line.center(width) for line in top_box.lines]
        bottom_lines = [line.center(width) for line in bottom_box.lines]
    else:
        width = max(top_box.width, bottom_box.width)
        top_lines = [line.ljust(width) for line in top_box.lines]
        bottom_lines = [line.ljust(width) for line in bottom_box.lines]
    return Box.from_lines(top_lines + bottom_lines, baseline=top_box.height - 1)


def box_pad_vertical(box: Box, top: int = 0, bottom: int = 0) -> Box:
    """在Box上下添加空白行"""
    lines = ([' ' * box.width] * top) + box.lines + ([' ' * box.width] * bottom)
    return Box.from_lines(lines, baseline=box.baseline + top)


def box_pad_horizontal(box: Box, left: int = 0, right: int = 0) -> Box:
    """在Box左右添加空格"""
    lines = [' ' * left + line + ' ' * right for line in box.lines]
    return Box.from_lines(lines, baseline=box.baseline)


# =====================================================================
# AST节点定义
# =====================================================================

class ASTNode(ABC):
    @abstractmethod
    def render(self, unicode_mode: bool = False) -> Box:
        ...


@dataclass
class NumberNode(ASTNode):
    value: str

    def render(self, unicode_mode: bool = False) -> Box:
        return Box.from_string(self.value)


@dataclass
class VariableNode(ASTNode):
    name: str

    def render(self, unicode_mode: bool = False) -> Box:
        return Box.from_string(self.name)


@dataclass
class SymbolNode(ASTNode):
    ascii_sym: str
    unicode_sym: str = ""

    def render(self, unicode_mode: bool = False) -> Box:
        sym = self.unicode_sym if (unicode_mode and self.unicode_sym) else self.ascii_sym
        return Box.from_string(sym)


@dataclass
class OperatorNode(ASTNode):
    op: str

    def render(self, unicode_mode: bool = False) -> Box:
        op_map = {
            '+': ('+', '+'),
            '-': ('-', '-'),
            '*': ('*', '×'),
            '/': ('/', '÷'),
            '=': ('=', '='),
            '<': ('<', '<'),
            '>': ('>', '>'),
            '!': ('!', '!'),
        }
        ascii_op, unicode_op = op_map.get(self.op, (self.op, self.op))
        sym = unicode_op if unicode_mode else ascii_op
        return Box.from_string(' ' + sym + ' ')


@dataclass
class BinOpNode(ASTNode):
    left: ASTNode
    op: str
    right: ASTNode

    def render(self, unicode_mode: bool = False) -> Box:
        left_box = self.left.render(unicode_mode)
        op_box = OperatorNode(self.op).render(unicode_mode)
        right_box = self.right.render(unicode_mode)
        return box_hconcat([left_box, op_box, right_box])


@dataclass
class UnaryOpNode(ASTNode):
    op: str
    operand: ASTNode

    def render(self, unicode_mode: bool = False) -> Box:
        if self.op == '-':
            neg_box = Box.from_string('-')
            operand_box = self.operand.render(unicode_mode)
            return box_hconcat([neg_box, operand_box])
        elif self.op == '+':
            return self.operand.render(unicode_mode)
        return self.operand.render(unicode_mode)


@dataclass
class FractionNode(ASTNode):
    numerator: ASTNode
    denominator: ASTNode
    nest_level: int = 0

    def render(self, unicode_mode: bool = False) -> Box:
        num_box = self.numerator.render(unicode_mode)
        den_box = self.denominator.render(unicode_mode)

        content_width = max(num_box.width, den_box.width)
        width = content_width + 2

        num_padded = Box.from_lines(
            [line.center(content_width) for line in num_box.lines],
            baseline=num_box.baseline
        )
        num_padded = box_pad_horizontal(num_padded, 1, 1)

        den_padded = Box.from_lines(
            [line.center(content_width) for line in den_box.lines],
            baseline=den_box.baseline
        )
        den_padded = box_pad_horizontal(den_padded, 1, 1)

        hline = '─' * width if unicode_mode else '-' * width

        result_lines = num_padded.lines + [hline] + den_padded.lines
        baseline = num_padded.height
        return Box.from_lines(result_lines, baseline=baseline)


@dataclass
class SuperscriptNode(ASTNode):
    base: ASTNode
    sup: ASTNode

    def render(self, unicode_mode: bool = False) -> Box:
        base_box = self.base.render(unicode_mode)
        sup_box = self.sup.render(unicode_mode)

        if base_box.height <= 1 and sup_box.height <= 1:
            return Box.from_lines([
                ' ' * base_box.width + sup_box.lines[0],
                base_box.lines[0] + ' ' * sup_box.width
            ], baseline=1)

        sup_height = sup_box.height
        base_height = base_box.height
        shift = max(1, base_height - sup_height)

        total_height = max(base_height, sup_height + shift)
        result_lines = []
        for i in range(total_height):
            base_row = i
            sup_row = i - shift
            base_str = base_box.lines[base_row] if 0 <= base_row < base_height else ' ' * base_box.width
            sup_str = sup_box.lines[sup_row] if 0 <= sup_row < sup_height else ' ' * sup_box.width
            result_lines.append(base_str + sup_str)

        baseline = base_box.baseline
        return Box.from_lines(result_lines, baseline=baseline)


@dataclass
class SubscriptNode(ASTNode):
    base: ASTNode
    sub: ASTNode

    def render(self, unicode_mode: bool = False) -> Box:
        base_box = self.base.render(unicode_mode)
        sub_box = self.sub.render(unicode_mode)

        if base_box.height <= 1 and sub_box.height <= 1:
            return Box.from_lines([
                base_box.lines[0] + ' ' * sub_box.width,
                ' ' * base_box.width + sub_box.lines[0]
            ], baseline=0)

        base_height = base_box.height
        sub_height = sub_box.height
        shift = max(0, base_height - 1)

        total_height = max(base_height, sub_height + shift)
        result_lines = []
        for i in range(total_height):
            base_row = i
            sub_row = i - shift
            base_str = base_box.lines[base_row] if 0 <= base_row < base_height else ' ' * base_box.width
            sub_str = sub_box.lines[sub_row] if 0 <= sub_row < sub_height else ' ' * sub_box.width
            result_lines.append(base_str + sub_str)

        baseline = base_box.baseline
        return Box.from_lines(result_lines, baseline=baseline)


@dataclass
class SubSuperscriptNode(ASTNode):
    base: ASTNode
    sub: ASTNode
    sup: ASTNode

    def render(self, unicode_mode: bool = False) -> Box:
        sub_box = SubscriptNode(self.base, self.sub).render(unicode_mode)
        base_width = self.base.render(unicode_mode).width
        sup_box = self.sup.render(unicode_mode)

        lines = list(sub_box.lines)
        if sup_box.height == 1:
            while len(lines) < sub_box.height + 1:
                lines.insert(0, ' ' * sub_box.width)
            lines[0] = ' ' * base_width + sup_box.lines[0] + ' ' * (sub_box.width - base_width - sup_box.width)
        return Box.from_lines(lines, baseline=sub_box.baseline + (sup_box.height if sup_box.height == 1 else 0))


@dataclass
class SqrtNode(ASTNode):
    argument: ASTNode
    degree: Optional[ASTNode] = None

    def render(self, unicode_mode: bool = False) -> Box:
        arg_box = self.argument.render(unicode_mode)
        padded = box_pad_horizontal(arg_box, 1, 1)
        h = padded.height
        w = padded.width

        if unicode_mode:
            sqrt_lines = []
            top_bar = '─' * w
            sqrt_lines.append(' ' + top_bar)
            for i in range(h):
                if i == 0:
                    prefix = '┌'
                elif i == h - 1:
                    prefix = '╰'
                else:
                    prefix = '│'
                sqrt_lines.append(prefix + padded.lines[i])

            if self.degree:
                deg_box = self.degree.render(unicode_mode)
                deg_lines = list(deg_box.lines)
                while len(deg_lines) < len(sqrt_lines):
                    deg_lines.insert(0, ' ' * deg_box.width)
                combined = []
                for i in range(len(sqrt_lines)):
                    if i < len(deg_lines):
                        combined.append(deg_lines[i] + sqrt_lines[i])
                    else:
                        combined.append(' ' * deg_box.width + sqrt_lines[i])
                return Box.from_lines(combined, baseline=1 + (h // 2))

            return Box.from_lines(sqrt_lines, baseline=1 + (h // 2))
        else:
            sqrt_lines = []
            top_line = ' ' * h + '-' * w
            sqrt_lines.append(top_line)
            for i in range(h):
                spaces = ' ' * (h - 1 - i)
                if i == h - 1:
                    prefix = spaces + '\\'
                else:
                    prefix = spaces + ' ' + ' ' * i
                    prefix = ' ' * (h - i)
                    if i == 0:
                        prefix = ' ' * (h - 1) + '/'
                    else:
                        prefix = ' ' * (h - 1 - i) + '\\'
                sqrt_lines.append(prefix + padded.lines[i])

            if self.degree:
                deg_box = self.degree.render(unicode_mode)
                deg_lines = list(deg_box.lines)
                while len(deg_lines) < len(sqrt_lines):
                    deg_lines.insert(0, ' ' * deg_box.width)
                combined = []
                for i in range(len(sqrt_lines)):
                    if i < len(deg_lines):
                        combined.append(deg_lines[i] + sqrt_lines[i])
                    else:
                        combined.append(' ' * deg_box.width + sqrt_lines[i])
                return Box.from_lines(combined, baseline=1 + (h // 2))

            return Box.from_lines(sqrt_lines, baseline=1 + (h // 2))


@dataclass
class SumNode(ASTNode):
    lower: Optional[ASTNode] = None
    upper: Optional[ASTNode] = None
    nest_level: int = 0

    def render(self, unicode_mode: bool = False) -> Box:
        if unicode_mode:
            sigma_lines = [
                ' ________ ',
                '╲        ╱',
                ' ╲      ╱ ',
                '  ╲    ╱  ',
                '   ╲  ╱   ',
                '    ╲╱    ',
            ]
        else:
            sigma_lines = [
                '--------',
                '\\      /',
                ' \\    / ',
                '  \\/\\/  ',
                ' /    \\ ',
                '/      \\',
                '--------',
            ]

        sigma_box = Box.from_lines(sigma_lines, baseline=len(sigma_lines) // 2)

        upper_box = self.upper.render(unicode_mode) if self.upper else None
        lower_box = self.lower.render(unicode_mode) if self.lower else None

        sigma_width = sigma_box.width
        upper_width = upper_box.width if upper_box else 0
        lower_width = lower_box.width if lower_box else 0
        total_width = max(sigma_width, upper_width, lower_width)

        result_lines = []
        baseline_offset = 0

        if upper_box:
            pad_left = (total_width - upper_width) // 2
            pad_right = total_width - upper_width - pad_left
            for line in upper_box.lines:
                result_lines.append(' ' * pad_left + line + ' ' * pad_right)
            baseline_offset += upper_box.height

        sigma_pad_left = (total_width - sigma_width) // 2
        sigma_pad_right = total_width - sigma_width - sigma_pad_left
        for i, line in enumerate(sigma_box.lines):
            result_lines.append(' ' * sigma_pad_left + line + ' ' * sigma_pad_right)

        sigma_baseline = baseline_offset + sigma_box.baseline

        if lower_box:
            pad_left = (total_width - lower_width) // 2
            pad_right = total_width - lower_width - pad_left
            for line in lower_box.lines:
                result_lines.append(' ' * pad_left + line + ' ' * pad_right)

        return Box.from_lines(result_lines, baseline=sigma_baseline)


@dataclass
class IntegralNode(ASTNode):
    lower: Optional[ASTNode] = None
    upper: Optional[ASTNode] = None
    nest_level: int = 0

    def render(self, unicode_mode: bool = False) -> Box:
        if unicode_mode:
            int_lines = [
                '    ╮',
                '    │',
                '    │',
                '    │',
                '    │',
                '    │',
                '    ╯',
            ]
        else:
            int_lines = [
                '   /',
                '  / ',
                ' /  ',
                '|   ',
                '|   ',
                '|   ',
                ' \\  ',
                '  \\ ',
                '   \\',
            ]

        int_box = Box.from_lines(int_lines, baseline=len(int_lines) // 2)

        upper_box = self.upper.render(unicode_mode) if self.upper else None
        lower_box = self.lower.render(unicode_mode) if self.lower else None

        int_width = int_box.width
        upper_width = upper_box.width if upper_box else 0
        lower_width = lower_box.width if lower_box else 0

        result_lines = []
        baseline_offset = 0

        if upper_box:
            pad_left = int_width
            for line in upper_box.lines:
                result_lines.append(' ' * pad_left + line)
            baseline_offset += upper_box.height

        for i, line in enumerate(int_box.lines):
            if i == 0 and upper_box:
                result_lines.append(line + ' ' * upper_width)
            elif i == len(int_box.lines) - 1 and lower_box:
                result_lines.append(line + ' ' * lower_width)
            else:
                result_lines.append(line)

        int_baseline = baseline_offset + int_box.baseline

        if lower_box:
            pad_left = int_width
            for line in lower_box.lines:
                result_lines.append(' ' * pad_left + line)

        return Box.from_lines(result_lines, baseline=int_baseline)


@dataclass
class MatrixNode(ASTNode):
    rows: List[List[ASTNode]]
    env_type: str = "matrix"  # matrix, pmatrix, bmatrix, vmatrix, det
    nest_level: int = 0

    def render(self, unicode_mode: bool = False) -> Box:
        cell_boxes = []
        for row in self.rows:
            row_boxes = [cell.render(unicode_mode) for cell in row]
            cell_boxes.append(row_boxes)

        if not cell_boxes:
            return Box.from_lines([""])

        num_cols = max(len(row) for row in cell_boxes)
        col_widths = [0] * num_cols
        col_heights = [0] * num_cols
        row_heights = [0] * len(cell_boxes)
        row_baselines = [0] * len(cell_boxes)

        for i, row in enumerate(cell_boxes):
            for j, cell in enumerate(row):
                col_widths[j] = max(col_widths[j], cell.width)
                row_heights[i] = max(row_heights[i], cell.height)

        for j in range(num_cols):
            for i, row in enumerate(cell_boxes):
                if j < len(row):
                    col_heights[j] = max(col_heights[j], row[j].height)

        for i, row in enumerate(cell_boxes):
            max_base = 0
            for j, cell in enumerate(row):
                needed_pad_top = (row_heights[i] - cell.height) // 2
                max_base = max(max_base, cell.baseline + needed_pad_top)
            row_baselines[i] = max_base

        padded_rows = []
        for i, row in enumerate(cell_boxes):
            padded_cells = []
            for j in range(num_cols):
                if j < len(row):
                    cell = row[j]
                else:
                    cell = Box.from_string("")
                h_pad_left = (col_widths[j] - cell.width) // 2
                h_pad_right = col_widths[j] - cell.width - h_pad_left
                v_pad_top = row_baselines[i] - cell.baseline
                v_pad_bottom = row_heights[i] - cell.height - v_pad_top
                if v_pad_top < 0:
                    v_pad_top = 0
                if v_pad_bottom < 0:
                    v_pad_bottom = 0
                padded = box_pad_vertical(
                    box_pad_horizontal(cell, h_pad_left, h_pad_right),
                    v_pad_top, v_pad_bottom
                )
                padded_cells.append(padded)
            padded_rows.append(padded_cells)

        rendered_rows = []
        for row_cells in padded_rows:
            sep_box = Box.from_string("  ")
            parts = []
            for idx, cell in enumerate(row_cells):
                if idx > 0:
                    parts.append(sep_box)
                parts.append(cell)
            rendered_rows.append(box_hconcat(parts))

        total_content = rendered_rows[0]
        for r in rendered_rows[1:]:
            total_content = box_vconcat(total_content, r, center=False)

        total_content = box_pad_vertical(total_content, 0, 0)

        if self.env_type in ("vmatrix", "det"):
            h = total_content.height
            new_lines = []
            for i in range(h):
                l, r = '|', '|'
                new_lines.append(l + ' ' + total_content.lines[i] + ' ' + r)
            return Box.from_lines(new_lines, baseline=total_content.baseline)

        elif self.env_type == "bmatrix":
            if unicode_mode:
                left_char, right_char = '┌', '┐'
                left_mid, right_mid = '│', '│'
                left_bot, right_bot = '└', '┘'
            else:
                left_char, right_char = '[', ']'
                left_mid, right_mid = '|', '|'
                left_bot, right_bot = '[', ']'

            h = total_content.height
            w = total_content.width
            new_lines = []
            for i in range(h):
                if h == 1:
                    l, r = '[', ']'
                elif i == 0:
                    l, r = left_char, right_char
                elif i == h - 1:
                    l, r = left_bot, right_bot
                else:
                    l, r = left_mid, right_mid
                new_lines.append(l + ' ' + total_content.lines[i] + ' ' + r)
            return Box.from_lines(new_lines, baseline=total_content.baseline + (0 if h <= 1 else 0))

        elif self.env_type == "pmatrix":
            h = total_content.height
            w = total_content.width
            new_lines = []
            for i in range(h):
                if h == 1:
                    l, r = '(', ')'
                elif i == 0:
                    l, r = '⎛', '⎞' if unicode_mode else '(', ')'
                elif i == h - 1:
                    l, r = '⎝', '⎠' if unicode_mode else '(', ')'
                else:
                    l, r = '⎜', '⎟' if unicode_mode else '(', ')'
                new_lines.append(l + ' ' + total_content.lines[i] + ' ' + r)
            return Box.from_lines(new_lines, baseline=total_content.baseline)

        return total_content


@dataclass
class ParenNode(ASTNode):
    left: str
    content: ASTNode
    right: str
    nest_level: int = 0

    def render(self, unicode_mode: bool = False) -> Box:
        content_box = self.content.render(unicode_mode)
        h = content_box.height

        extra_height = self.nest_level
        total_height = h + 2 * extra_height

        if self.left == '(' and self.right == ')':
            if total_height == 1:
                left_lines = ['(']
                right_lines = [')']
            else:
                if unicode_mode:
                    left_lines = ['⎛'] + ['⎜'] * (total_height - 2) + ['⎝']
                    right_lines = ['⎞'] + ['⎟'] * (total_height - 2) + ['⎠']
                else:
                    left_lines = ['/'] + ['|'] * (total_height - 2) + ['\\']
                    right_lines = ['\\'] + ['|'] * (total_height - 2) + ['/']
        elif self.left == '[' and self.right == ']':
            if total_height == 1:
                left_lines = ['[']
                right_lines = [']']
            else:
                if unicode_mode:
                    left_lines = ['┌'] + ['│'] * (total_height - 2) + ['└']
                    right_lines = ['┐'] + ['│'] * (total_height - 2) + ['┘']
                else:
                    left_lines = ['['] + ['|'] * (total_height - 2) + [']']
                    right_lines = [']'] + ['|'] * (total_height - 2) + ['[']
        elif self.left == '{' and self.right == '}':
            if total_height == 1:
                left_lines = ['{']
                right_lines = ['}']
            else:
                if unicode_mode:
                    left_lines = ['⎧'] + ['⎪'] * max(0, total_height - 2) + ['⎩']
                    right_lines = ['⎫'] + ['⎪'] * max(0, total_height - 2) + ['⎭']
                else:
                    left_lines = ['{'] + ['|'] * (total_height - 2) + ['}']
                    right_lines = ['}'] + ['|'] * (total_height - 2) + ['{']
        elif self.left == '|' and self.right == '|':
            left_lines = ['|'] * total_height
            right_lines = ['|'] * total_height
        else:
            left_lines = [self.left] * total_height
            right_lines = [self.right] * total_height

        content_padded = box_pad_vertical(content_box, extra_height, extra_height)

        left_box = Box.from_lines(left_lines, baseline=total_height // 2 if total_height > 1 else 0)
        right_box = Box.from_lines(right_lines, baseline=total_height // 2 if total_height > 1 else 0)

        space_box = Box.from_string(" ")
        return box_hconcat([left_box, space_box, content_padded, space_box, right_box])


@dataclass
class ExprListNode(ASTNode):
    items: List[ASTNode]

    def render(self, unicode_mode: bool = False) -> Box:
        rendered = [item.render(unicode_mode) for item in self.items]
        return box_hconcat(rendered)


@dataclass
class AlignNode(ASTNode):
    rows: List[List[ASTNode]]
    numbered: bool = True
    start_number: int = 1

    def render(self, unicode_mode: bool = False) -> Box:
        if not self.rows:
            return Box.from_lines([""])

        rendered_rows = []
        for row in self.rows:
            rendered_cells = [cell.render(unicode_mode) for cell in row]
            rendered_rows.append(rendered_cells)

        num_cols = max(len(row) for row in rendered_rows)
        col_widths = [0] * num_cols
        col_baselines = [0] * num_cols

        for row in rendered_rows:
            for j, cell in enumerate(row):
                col_widths[j] = max(col_widths[j], cell.width)

        aligned_row_boxes = []
        row_heights = []
        for i, row in enumerate(rendered_rows):
            padded_cells = []
            row_height = 0
            for j in range(num_cols):
                if j < len(row):
                    cell = row[j]
                else:
                    cell = Box.from_string("")
                h_pad = col_widths[j] - cell.width
                if j % 2 == 0:
                    padded = box_pad_horizontal(cell, 0, h_pad)
                else:
                    padded = box_pad_horizontal(cell, h_pad, 0)
                padded_cells.append(padded)
                row_height = max(row_height, padded.height)

            aligned_row = box_hconcat(padded_cells)

            if self.numbered:
                num_str = f"({self.start_number + i})"
                num_box = Box.from_string(num_str)
                total_width = aligned_row.width + 4 + num_box.width
                lines = []
                for k in range(max(aligned_row.height, num_box.height)):
                    row_line = aligned_row.lines[k] if k < aligned_row.height else ' ' * aligned_row.width
                    num_line = num_box.lines[k] if k < num_box.height else ' ' * num_box.width
                    lines.append(row_line + ' ' * 4 + num_line.rjust(total_width - aligned_row.width - 4))
                baseline = aligned_row.baseline if aligned_row.baseline < len(lines) else len(lines) // 2
                aligned_row = Box.from_lines(lines, baseline=baseline)

            aligned_row_boxes.append(aligned_row)
            row_heights.append(aligned_row.height)

        result = aligned_row_boxes[0]
        for r in aligned_row_boxes[1:]:
            result = box_vconcat(result, r, center=False)

        return result


@dataclass
class CasesNode(ASTNode):
    rows: List[Tuple[ASTNode, ASTNode]]

    def render(self, unicode_mode: bool = False) -> Box:
        if not self.rows:
            return Box.from_lines([""])

        rendered_rows = []
        max_expr_width = 0
        max_cond_width = 0
        row_heights = []

        for expr, cond in self.rows:
            expr_box = expr.render(unicode_mode)
            cond_box = cond.render(unicode_mode)
            rendered_rows.append((expr_box, cond_box))
            max_expr_width = max(max_expr_width, expr_box.width)
            max_cond_width = max(max_cond_width, cond_box.width)
            row_heights.append(max(expr_box.height, cond_box.height))

        total_height = sum(row_heights)
        brace_lines = self._render_brace(total_height, unicode_mode)

        content_lines = []
        for i, (expr_box, cond_box) in enumerate(rendered_rows):
            h = row_heights[i]
            for k in range(h):
                expr_line = expr_box.lines[k] if k < expr_box.height else ' ' * expr_box.width
                cond_line = cond_box.lines[k] if k < cond_box.height else ' ' * cond_box.width
                content_lines.append(' ' + expr_line.ljust(max_expr_width) + '   ' + cond_line.ljust(max_cond_width))

        result_lines = []
        for i in range(total_height):
            brace_part = brace_lines[i] if i < len(brace_lines) else ' ' * 2
            result_lines.append(brace_part + content_lines[i])

        baseline = total_height // 2
        return Box.from_lines(result_lines, baseline=baseline)

    def _render_brace(self, height: int, unicode_mode: bool) -> List[str]:
        if height == 1:
            return ['{']
        if height == 2:
            return ['{', '{']

        brace = []
        mid = height // 2

        if unicode_mode:
            for i in range(height):
                if i == 0:
                    brace.append('⎧')
                elif i == mid:
                    brace.append('⎨')
                elif i == height - 1:
                    brace.append('⎩')
                else:
                    brace.append('⎪')
        else:
            for i in range(height):
                if i == 0:
                    brace.append('{')
                elif i == height - 1:
                    brace.append('{')
                else:
                    brace.append('|')

        return [b.ljust(2) for b in brace]


@dataclass
class EquationNode(ASTNode):
    content: ASTNode
    number: Optional[int] = None

    def render(self, unicode_mode: bool = False) -> Box:
        content_box = self.content.render(unicode_mode)
        if self.number is None:
            return content_box

        num_str = f"({self.number})"
        num_box = Box.from_string(num_str)
        total_width = content_box.width + 4 + num_box.width

        lines = []
        for k in range(max(content_box.height, num_box.height)):
            content_line = content_box.lines[k] if k < content_box.height else ' ' * content_box.width
            num_line = num_box.lines[k] if k < num_box.height else ' ' * num_box.width
            lines.append(content_line + ' ' * 4 + num_line.rjust(total_width - content_box.width - 4))

        baseline = content_box.baseline if content_box.baseline < len(lines) else len(lines) // 2
        return Box.from_lines(lines, baseline=baseline)


# =====================================================================
# 希腊字母和符号映射
# =====================================================================

GREEK_LETTERS = {
    'alpha': ('α', 'a'),
    'beta': ('β', 'b'),
    'gamma': ('γ', 'g'),
    'delta': ('δ', 'd'),
    'epsilon': ('ε', 'e'),
    'zeta': ('ζ', 'z'),
    'eta': ('η', 'h'),
    'theta': ('θ', 'th'),
    'iota': ('ι', 'i'),
    'kappa': ('κ', 'k'),
    'lambda': ('λ', 'l'),
    'mu': ('μ', 'm'),
    'nu': ('ν', 'n'),
    'xi': ('ξ', 'x'),
    'omicron': ('ο', 'o'),
    'pi': ('π', 'p'),
    'rho': ('ρ', 'r'),
    'sigma': ('σ', 's'),
    'tau': ('τ', 't'),
    'upsilon': ('υ', 'u'),
    'phi': ('φ', 'ph'),
    'chi': ('χ', 'ch'),
    'psi': ('ψ', 'ps'),
    'omega': ('ω', 'w'),
    'Gamma': ('Γ', 'G'),
    'Delta': ('Δ', 'D'),
    'Theta': ('Θ', 'TH'),
    'Lambda': ('Λ', 'L'),
    'Xi': ('Ξ', 'X'),
    'Pi': ('Π', 'P'),
    'Sigma': ('Σ', 'S'),
    'Upsilon': ('Υ', 'U'),
    'Phi': ('Φ', 'PH'),
    'Psi': ('Ψ', 'PS'),
    'Omega': ('Ω', 'W'),
}

SPECIAL_SYMBOLS = {
    'infty': ('∞', 'inf'),
    'neq': ('≠', '!='),
    'leq': ('≤', '<='),
    'geq': ('≥', '>='),
    'le': ('≤', '<='),
    'ge': ('≥', '>='),
    'pm': ('±', '+/-'),
    'mp': ('∓', '-/+'),
    'times': ('×', '*'),
    'div': ('÷', '/'),
    'cdot': ('·', '.'),
    'circ': ('°', 'o'),
    'approx': ('≈', '~='),
    'sim': ('~', '~'),
    'equiv': ('≡', '=='),
    'perp': ('⊥', '_|_'),
    'parallel': ('∥', '||'),
    'angle': ('∠', '<'),
    'prime': ("'", "'"),
    'emptyset': ('∅', '{}'),
    'forall': ('∀', 'FA'),
    'exists': ('∃', 'EX'),
    'neg': ('¬', '~'),
    'wedge': ('∧', '^'),
    'vee': ('∨', 'v'),
    'implies': ('⇒', '=>'),
    'iff': ('⇔', '<=>'),
    'to': ('→', '->'),
    'rightarrow': ('→', '->'),
    'leftarrow': ('←', '<-'),
    'leftrightarrow': ('↔', '<->'),
    'mapsto': ('↦', '|->'),
    'sum': ('Σ', 'sum'),
    'prod': ('Π', 'prod'),
    'int': ('∫', 'int'),
    'partial': ('∂', 'd'),
    'nabla': ('∇', 'Nab'),
    'infty': ('∞', 'inf'),
    'ell': ('ℓ', 'l'),
    'Re': ('ℜ', 'Re'),
    'Im': ('ℑ', 'Im'),
    'hbar': ('ℏ', 'h'),
    'ldots': ('...', '...'),
    'cdots': ('⋯', '...'),
    'vdots': ('⋮', '...'),
    'ddots': ('⋱', '...'),
}


# =====================================================================
# 宏展开系统 (Macro System)
# =====================================================================

@dataclass
class MacroDefinition:
    name: str
    num_params: int
    definition: str
    default_args: Dict[int, str] = field(default_factory=dict)


class MacroExpander:
    def __init__(self):
        self.macros: Dict[str, MacroDefinition] = {}

    def define(self, name: str, num_params: int, definition: str):
        self.macros[name] = MacroDefinition(name, num_params, definition)

    def load_from_file(self, filepath: str):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        self.parse_newcommand(line)
        except Exception as e:
            print(f"[警告] 加载宏文件失败: {e}", file=sys.stderr)

    def parse_newcommand(self, text: str) -> bool:
        pattern = r'\\newcommand\{\\([a-zA-Z]+)\}(?:\[(\d+)\])?(?:\[([^\]]*)\])?\{([^}]*)\}'
        match = re.match(pattern, text)
        if not match:
            return False

        name = match.group(1)
        num_params = int(match.group(2)) if match.group(2) else 0
        default = match.group(3)
        definition = match.group(4)

        default_args = {}
        if default is not None and num_params > 0:
            default_args[1] = default

        self.define(name, num_params, definition)
        return True

    def expand(self, text: str) -> str:
        result = text
        max_iterations = 100
        for _ in range(max_iterations):
            expanded, changed = self._expand_once(result)
            result = expanded
            if not changed:
                break
        return result

    def _expand_once(self, text: str) -> Tuple[str, bool]:
        changed = False
        result_parts: List[str] = []
        pos = 0

        while pos < len(text):
            if text[pos] == '\\':
                match = re.match(r'\\([a-zA-Z]+)', text[pos:])
                if match:
                    cmd_name = match.group(1)
                    if cmd_name == 'newcommand':
                        end_pos = self._find_matching_brace(text, pos + len('\\newcommand'))
                        if end_pos > 0:
                            full_def = text[pos:end_pos + 1]
                            self.parse_newcommand(full_def)
                            pos = end_pos + 1
                            changed = True
                            continue

                    if cmd_name in self.macros:
                        macro = self.macros[cmd_name]
                        args: List[str] = []
                        current_pos = pos + len(match.group(0))

                        if macro.num_params > 0:
                            for i in range(macro.num_params):
                                if current_pos < len(text) and text[current_pos] == '[':
                                    end_bracket = self._find_matching_bracket(text, current_pos)
                                    if end_bracket > 0:
                                        args.append(text[current_pos + 1:end_bracket])
                                        current_pos = end_bracket + 1
                                    else:
                                        args.append(macro.default_args.get(i + 1, ''))
                                        break
                                elif current_pos < len(text) and text[current_pos] == '{':
                                    end_brace = self._find_matching_brace(text, current_pos)
                                    if end_brace > 0:
                                        args.append(text[current_pos + 1:end_brace])
                                        current_pos = end_brace + 1
                                    else:
                                        args.append(macro.default_args.get(i + 1, ''))
                                        break
                                else:
                                    default_val = macro.default_args.get(i + 1)
                                    if default_val is not None:
                                        args.append(default_val)
                                    else:
                                        break
                        else:
                            if current_pos < len(text) and text[current_pos] == '{':
                                end_brace = self._find_matching_brace(text, current_pos)
                                if end_brace > 0:
                                    current_pos = end_brace + 1

                        if len(args) == macro.num_params:
                            expanded_macro = macro.definition
                            for i, arg in enumerate(args, 1):
                                expanded_macro = expanded_macro.replace(f'#{i}', arg)
                            result_parts.append(expanded_macro)
                            pos = current_pos
                            changed = True
                            continue

                result_parts.append(text[pos])
                pos += 1
            else:
                result_parts.append(text[pos])
                pos += 1

        return ''.join(result_parts), changed

    def _find_matching_brace(self, text: str, start: int) -> int:
        if start >= len(text) or text[start] != '{':
            return -1
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    return i
        return -1

    def _find_matching_bracket(self, text: str, start: int) -> int:
        if start >= len(text) or text[start] != '[':
            return -1
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '[':
                depth += 1
            elif text[i] == ']':
                depth -= 1
                if depth == 0:
                    return i
        return -1


# =====================================================================
# 词法分析器 (Tokenizer)
# =====================================================================

class Token:
    def __init__(self, type_: str, value: str, pos: int = 0):
        self.type = type_
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f"Token({self.type}, {repr(self.value)})"


class Tokenizer:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.tokens: List[Token] = []

    def tokenize(self) -> List[Token]:
        while self.pos < len(self.text):
            self.skip_whitespace()
            if self.pos >= len(self.text):
                break

            ch = self.text[self.pos]

            if ch == '\\':
                self.read_command()
            elif ch.isdigit() or (ch == '.' and self.peek_next().isdigit()):
                self.read_number()
            elif ch.isalpha():
                self.tokens.append(Token('VAR', ch, self.pos))
                self.pos += 1
            elif ch in '+-*/=<>!':
                self.tokens.append(Token('OP', ch, self.pos))
                self.pos += 1
            elif ch in '()[]{}':
                self.tokens.append(Token('PAREN', ch, self.pos))
                self.pos += 1
            elif ch in '^_':
                self.tokens.append(Token('SUPSUB', ch, self.pos))
                self.pos += 1
            elif ch == '&':
                self.tokens.append(Token('AMP', ch, self.pos))
                self.pos += 1
            elif ch == '\\':
                self.pos += 1
            elif ch == ',':
                self.tokens.append(Token('COMMA', ch, self.pos))
                self.pos += 1
            elif ch == ';':
                self.tokens.append(Token('SEMI', ch, self.pos))
                self.pos += 1
            elif ch == '|':
                self.tokens.append(Token('PIPE', ch, self.pos))
                self.pos += 1
            elif ch == '%':
                while self.pos < len(self.text) and self.text[self.pos] != '\n':
                    self.pos += 1
            else:
                self.pos += 1

        self.tokens.append(Token('EOF', '', self.pos))
        return self.tokens

    def skip_whitespace(self):
        while self.pos < len(self.text) and self.text[self.pos] in ' \t\n\r':
            self.pos += 1

    def peek_next(self) -> str:
        if self.pos + 1 < len(self.text):
            return self.text[self.pos + 1]
        return ''

    def read_number(self):
        start = self.pos
        has_dot = False
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch.isdigit():
                self.pos += 1
            elif ch == '.' and not has_dot:
                has_dot = True
                self.pos += 1
            else:
                break
        self.tokens.append(Token('NUM', self.text[start:self.pos], start))

    def read_command(self):
        start = self.pos
        self.pos += 1  # skip backslash

        if self.pos < len(self.text) and not self.text[self.pos].isalpha():
            self.tokens.append(Token('CMD', self.text[start:self.pos + 1], start))
            self.pos += 1
            return

        cmd_start = self.pos
        while self.pos < len(self.text) and self.text[self.pos].isalpha():
            self.pos += 1

        cmd = self.text[cmd_start:self.pos]
        self.tokens.append(Token('CMD', cmd, start))


# =====================================================================
# 语法解析器 (Parser)
# =====================================================================

class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def current(self) -> Token:
        return self.tokens[self.pos]

    def consume(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, type_: str, value: Optional[str] = None) -> Token:
        tok = self.current()
        if tok.type != type_ or (value is not None and tok.value != value):
            raise SyntaxError(f"Expected {type_} {value}, got {tok}")
        return self.consume()

    def parse(self) -> ASTNode:
        node = self.parse_expr()
        return node

    def parse_expr(self) -> ASTNode:
        items = []
        stop_types = ('EOF', 'AMP', 'SEMI', 'PIPE')
        stop_cmds = ('end',)

        while True:
            tok = self.current()
            if tok.type in stop_types:
                break
            if tok.type == 'CMD' and tok.value in stop_cmds:
                break
            if tok.type == 'PAREN' and tok.value in ')}]':
                break

            item = self.parse_atom()
            if item is None:
                if tok.type == 'OP' and tok.value not in '+-':
                    break
                else:
                    break
            items.append(item)

            if self.current().type == 'OP' and self.current().value in '+-*/=<>':
                op = self.consume().value
                right = self.parse_expr()
                if isinstance(right, ExprListNode) and len(right.items) > 0:
                    items = [BinOpNode(ExprListNode(items), op, right.items[0])] + right.items[1:]
                else:
                    items = [BinOpNode(ExprListNode(items), op, right)]
                break

        if len(items) == 0:
            return NumberNode("0")
        if len(items) == 1:
            return items[0]
        return ExprListNode(items)

    def parse_atom(self) -> Optional[ASTNode]:
        tok = self.current()

        if tok.type == 'EOF':
            return None

        if tok.type == 'NUM':
            self.consume()
            node = NumberNode(tok.value)
            return self.parse_supsub(node)

        if tok.type == 'VAR':
            self.consume()
            node = VariableNode(tok.value)
            return self.parse_supsub(node)

        if tok.type == 'OP' and tok.value in '+-':
            self.consume()
            operand = self.parse_atom()
            if operand:
                return UnaryOpNode(tok.value, operand)
            return None

        if tok.type == 'PAREN' and tok.value in '({[':
            return self.parse_paren()

        if tok.type == 'PIPE':
            return self.parse_abs()

        if tok.type == 'CMD':
            return self.parse_command()

        if tok.type == 'COMMA':
            self.consume()
            return SymbolNode(',', ',')

        return None

    def parse_supsub(self, node: ASTNode) -> ASTNode:
        while self.current().type == 'SUPSUB':
            op_tok = self.consume()
            sub_node = self.parse_group_or_atom()

            if op_tok.value == '^':
                if self.current().type == 'SUPSUB' and self.current().value == '_':
                    self.consume()
                    sub = self.parse_group_or_atom()
                    node = SubSuperscriptNode(node, sub, sub_node)
                else:
                    node = SuperscriptNode(node, sub_node)
            elif op_tok.value == '_':
                if self.current().type == 'SUPSUB' and self.current().value == '^':
                    self.consume()
                    sup = self.parse_group_or_atom()
                    node = SubSuperscriptNode(node, sub_node, sup)
                else:
                    node = SubscriptNode(node, sub_node)
        return node

    def parse_group_or_atom(self) -> ASTNode:
        if self.current().type == 'PAREN' and self.current().value == '{':
            self.consume()
            expr = self.parse_expr()
            if self.current().type == 'PAREN' and self.current().value == '}':
                self.consume()
            return expr
        atom = self.parse_atom()
        return atom if atom else NumberNode("")

    def parse_paren(self) -> ASTNode:
        left_tok = self.consume()
        left_map = {'(': ')', '{': '}', '[': ']'}
        right_expected = left_map[left_tok.value]

        expr = self.parse_expr()

        if self.current().type == 'PAREN' and self.current().value == right_expected:
            self.consume()

        node = ParenNode(left_tok.value, expr, right_expected)
        return self.parse_supsub(node)

    def parse_abs(self) -> ASTNode:
        self.consume()
        expr = self.parse_expr()
        if self.current().type == 'PIPE':
            self.consume()
        node = ParenNode('|', expr, '|')
        return self.parse_supsub(node)

    def parse_command(self) -> Optional[ASTNode]:
        cmd = self.current().value

        if cmd in GREEK_LETTERS:
            self.consume()
            uni, asc = GREEK_LETTERS[cmd]
            node = SymbolNode(asc, uni)
            return self.parse_supsub(node)

        if cmd == 'sum':
            self.consume()
            lower = None
            upper = None
            if self.current().type == 'SUPSUB' and self.current().value == '_':
                self.consume()
                lower = self.parse_group_or_atom()
            if self.current().type == 'SUPSUB' and self.current().value == '^':
                self.consume()
                upper = self.parse_group_or_atom()
            elif self.current().type == 'SUPSUB' and self.current().value == '^' and upper is None:
                self.consume()
                upper = self.parse_group_or_atom()
                if self.current().type == 'SUPSUB' and self.current().value == '_' and lower is None:
                    self.consume()
                    lower = self.parse_group_or_atom()
            node = SumNode(lower, upper)
            return node

        if cmd == 'int':
            self.consume()
            lower = None
            upper = None
            if self.current().type == 'SUPSUB' and self.current().value == '_':
                self.consume()
                lower = self.parse_group_or_atom()
            if self.current().type == 'SUPSUB' and self.current().value == '^':
                self.consume()
                upper = self.parse_group_or_atom()
            elif self.current().type == 'SUPSUB' and self.current().value == '^' and upper is None:
                self.consume()
                upper = self.parse_group_or_atom()
                if self.current().type == 'SUPSUB' and self.current().value == '_' and lower is None:
                    self.consume()
                    lower = self.parse_group_or_atom()
            node = IntegralNode(lower, upper)
            return node

        if cmd in SPECIAL_SYMBOLS:
            self.consume()
            uni, asc = SPECIAL_SYMBOLS[cmd]
            node = SymbolNode(asc, uni)
            return self.parse_supsub(node)

        if cmd == 'frac':
            self.consume()
            num = self.parse_group_or_atom()
            den = self.parse_group_or_atom()
            node = FractionNode(num, den)
            return self.parse_supsub(node)

        if cmd == 'sqrt':
            self.consume()
            degree = None
            if self.current().type == 'SUPSUB' and self.current().value == '[':
                pass
            if self.current().type == 'PAREN' and self.current().value == '[':
                self.consume()
                degree = self.parse_expr()
                if self.current().type == 'PAREN' and self.current().value == ']':
                    self.consume()
            arg = self.parse_group_or_atom()
            node = SqrtNode(arg, degree)
            return self.parse_supsub(node)

        if cmd == 'begin':
            return self.parse_env()

        if cmd == 'left':
            self.consume()
            left_paren = self.current().value
            if self.current().type == 'PAREN' or self.current().type == 'PIPE':
                self.consume()
            else:
                left_paren = '('
            expr = self.parse_expr()
            right_paren = ')'
            if self.current().type == 'CMD' and self.current().value == 'right':
                self.consume()
                if self.current().type == 'PAREN' or self.current().type == 'PIPE':
                    right_paren = self.current().value
                    self.consume()
            return ParenNode(left_paren, expr, right_paren)

        if cmd == 'right':
            return None

        self.consume()
        return SymbolNode(cmd, cmd)

    def parse_env(self) -> ASTNode:
        self.expect('CMD', 'begin')
        self.expect('PAREN', '{')
        env_name = ''
        while self.current().type != 'PAREN' or self.current().value != '}':
            if self.current().type == 'VAR':
                env_name += self.consume().value
            elif self.current().type == 'CMD':
                env_name += self.consume().value
            else:
                self.consume()
        self.expect('PAREN', '}')

        if env_name == 'align' or env_name == 'align*':
            return self.parse_align_env(env_name)
        elif env_name == 'cases':
            return self.parse_cases_env()
        elif env_name == 'equation' or env_name == 'equation*':
            return self.parse_equation_env(env_name)
        else:
            return self.parse_matrix_env(env_name)

    def parse_align_env(self, env_name: str) -> ASTNode:
        numbered = (env_name != 'align*')
        rows: List[List[ASTNode]] = []
        current_row: List[ASTNode] = []
        current_cell_items: List[ASTNode] = []

        while not (self.current().type == 'CMD' and self.current().value == 'end'):
            tok = self.current()
            if tok.type == 'EOF':
                break

            if tok.type == 'AMP':
                self.consume()
                if current_cell_items:
                    current_row.append(ExprListNode(current_cell_items) if len(current_cell_items) > 1 else current_cell_items[0])
                else:
                    current_row.append(NumberNode(""))
                current_cell_items = []
                continue

            if tok.type == 'SEMI' or (tok.type == 'CMD' and tok.value == '\\\\'):
                self.consume()
                if current_cell_items:
                    current_row.append(ExprListNode(current_cell_items) if len(current_cell_items) > 1 else current_cell_items[0])
                else:
                    current_row.append(NumberNode(""))
                if current_row:
                    rows.append(current_row)
                current_row = []
                current_cell_items = []
                continue

            item = self.parse_atom()
            if item is not None:
                current_cell_items.append(item)
            else:
                self.consume()

        if current_cell_items:
            current_row.append(ExprListNode(current_cell_items) if len(current_cell_items) > 1 else current_cell_items[0])
        if current_row:
            rows.append(current_row)

        self._consume_end(env_name)
        return AlignNode(rows, numbered=numbered)

    def parse_cases_env(self) -> ASTNode:
        rows: List[Tuple[ASTNode, ASTNode]] = []
        current_expr_items: List[ASTNode] = []
        current_cond_items: List[ASTNode] = []
        in_condition = False

        while not (self.current().type == 'CMD' and self.current().value == 'end'):
            tok = self.current()
            if tok.type == 'EOF':
                break

            if tok.type == 'AMP':
                self.consume()
                in_condition = True
                continue

            if tok.type == 'SEMI' or (tok.type == 'CMD' and tok.value == '\\\\'):
                self.consume()
                expr = ExprListNode(current_expr_items) if len(current_expr_items) > 1 else (current_expr_items[0] if current_expr_items else NumberNode(""))
                cond = ExprListNode(current_cond_items) if len(current_cond_items) > 1 else (current_cond_items[0] if current_cond_items else NumberNode(""))
                rows.append((expr, cond))
                current_expr_items = []
                current_cond_items = []
                in_condition = False
                continue

            item = self.parse_atom()
            if item is not None:
                if in_condition:
                    current_cond_items.append(item)
                else:
                    current_expr_items.append(item)
            else:
                self.consume()

        if current_expr_items or current_cond_items:
            expr = ExprListNode(current_expr_items) if len(current_expr_items) > 1 else (current_expr_items[0] if current_expr_items else NumberNode(""))
            cond = ExprListNode(current_cond_items) if len(current_cond_items) > 1 else (current_cond_items[0] if current_cond_items else NumberNode(""))
            rows.append((expr, cond))

        self._consume_end('cases')
        return CasesNode(rows)

    def parse_equation_env(self, env_name: str) -> ASTNode:
        numbered = (env_name != 'equation*')
        expr_items: List[ASTNode] = []

        while not (self.current().type == 'CMD' and self.current().value == 'end'):
            tok = self.current()
            if tok.type == 'EOF':
                break

            if tok.type == 'SEMI' or (tok.type == 'CMD' and tok.value == '\\\\'):
                self.consume()
                continue

            item = self.parse_atom()
            if item is not None:
                expr_items.append(item)
            else:
                self.consume()

        self._consume_end(env_name)
        content = ExprListNode(expr_items) if len(expr_items) > 1 else (expr_items[0] if expr_items else NumberNode(""))
        return EquationNode(content, number=1 if numbered else None)

    def parse_matrix_env(self, env_name: str) -> ASTNode:
        rows: List[List[ASTNode]] = []
        current_row: List[ASTNode] = []
        current_cell_items: List[ASTNode] = []

        while not (self.current().type == 'CMD' and self.current().value == 'end'):
            tok = self.current()

            if tok.type == 'EOF':
                break

            if tok.type == 'CMD' and tok.value == 'end':
                break

            if tok.type == 'AMP':
                self.consume()
                if current_cell_items:
                    current_row.append(ExprListNode(current_cell_items) if len(current_cell_items) > 1 else current_cell_items[0])
                else:
                    current_row.append(NumberNode(""))
                current_cell_items = []
                continue

            if tok.type == 'SEMI' or (tok.type == 'CMD' and tok.value == '\\\\'):
                self.consume()
                if current_cell_items:
                    current_row.append(ExprListNode(current_cell_items) if len(current_cell_items) > 1 else current_cell_items[0])
                else:
                    current_row.append(NumberNode(""))
                if current_row:
                    rows.append(current_row)
                current_row = []
                current_cell_items = []
                continue

            if tok.type == 'CMD' and tok.value == '\\':
                self.consume()
                if current_cell_items:
                    current_row.append(ExprListNode(current_cell_items) if len(current_cell_items) > 1 else current_cell_items[0])
                else:
                    current_row.append(NumberNode(""))
                if current_row:
                    rows.append(current_row)
                current_row = []
                current_cell_items = []
                continue

            if tok.type == 'PAREN' and tok.value == '{' and len(current_cell_items) == 0:
                pass

            item = self.parse_atom()
            if item is not None:
                current_cell_items.append(item)
            else:
                self.consume()

        if current_cell_items:
            current_row.append(ExprListNode(current_cell_items) if len(current_cell_items) > 1 else current_cell_items[0])
        if current_row:
            rows.append(current_row)

        self._consume_end(env_name)

        env_type = env_name if env_name else "matrix"
        return MatrixNode(rows, env_type=env_type)

    def _consume_end(self, env_name: str):
        if self.current().type == 'CMD' and self.current().value == 'end':
            self.consume()
            if self.current().type == 'PAREN' and self.current().value == '{':
                self.consume()
                end_name = ''
                while self.current().type != 'PAREN' or self.current().value != '}':
                    if self.current().type == 'VAR':
                        end_name += self.consume().value
                    elif self.current().type == 'CMD':
                        end_name += self.consume().value
                    else:
                        self.consume()
                self.expect('PAREN', '}')


# =====================================================================
# 公式化简系统 (Formula Simplification)
# =====================================================================

def ast_to_latex(node: ASTNode) -> str:
    """将AST节点转换回LaTeX字符串"""
    if isinstance(node, NumberNode):
        return node.value
    elif isinstance(node, VariableNode):
        return node.name
    elif isinstance(node, SymbolNode):
        return node.unicode_sym if node.unicode_sym else node.ascii_sym
    elif isinstance(node, OperatorNode):
        return node.op
    elif isinstance(node, BinOpNode):
        left = ast_to_latex(node.left)
        right = ast_to_latex(node.right)
        return f"{left}{node.op}{right}"
    elif isinstance(node, UnaryOpNode):
        operand = ast_to_latex(node.operand)
        return f"{node.op}{operand}"
    elif isinstance(node, FractionNode):
        num = ast_to_latex(node.numerator)
        den = ast_to_latex(node.denominator)
        return f"\\frac{{{num}}}{{{den}}}"
    elif isinstance(node, SuperscriptNode):
        base = ast_to_latex(node.base)
        sup = ast_to_latex(node.sup)
        return f"{base}^{{{sup}}}"
    elif isinstance(node, SubscriptNode):
        base = ast_to_latex(node.base)
        sub = ast_to_latex(node.sub)
        return f"{base}_{{{sub}}}"
    elif isinstance(node, SubSuperscriptNode):
        base = ast_to_latex(node.base)
        sub = ast_to_latex(node.sub)
        sup = ast_to_latex(node.sup)
        return f"{base}_{{{sub}}}^{{{sup}}}"
    elif isinstance(node, SqrtNode):
        arg = ast_to_latex(node.argument)
        if node.degree:
            deg = ast_to_latex(node.degree)
            return f"\\sqrt[{deg}]{{{arg}}}"
        return f"\\sqrt{{{arg}}}"
    elif isinstance(node, SumNode):
        parts = ['\\sum']
        if node.lower:
            parts.append(f"_{{{ast_to_latex(node.lower)}}}")
        if node.upper:
            parts.append(f"^{{{ast_to_latex(node.upper)}}}")
        return ''.join(parts)
    elif isinstance(node, IntegralNode):
        parts = ['\\int']
        if node.lower:
            parts.append(f"_{{{ast_to_latex(node.lower)}}}")
        if node.upper:
            parts.append(f"^{{{ast_to_latex(node.upper)}}}")
        return ''.join(parts)
    elif isinstance(node, ParenNode):
        content = ast_to_latex(node.content)
        return f"{node.left}{content}{node.right}"
    elif isinstance(node, ExprListNode):
        return ''.join(ast_to_latex(item) for item in node.items)
    elif isinstance(node, MatrixNode):
        rows = []
        for row in node.rows:
            cells = [ast_to_latex(cell) for cell in row]
            rows.append(' & '.join(cells))
        env = node.env_type if node.env_type != 'det' else 'vmatrix'
        return f"\\begin{{{env}}}{' \\\\ '.join(rows)}\\end{{{env}}}"
    elif isinstance(node, AlignNode):
        rows = []
        for row in node.rows:
            cells = [ast_to_latex(cell) for cell in row]
            rows.append(' & '.join(cells))
        env = 'align' if node.numbered else 'align*'
        return f"\\begin{{{env}}}{' \\\\ '.join(rows)}\\end{{{env}}}"
    elif isinstance(node, CasesNode):
        rows = []
        for expr, cond in node.rows:
            rows.append(f"{ast_to_latex(expr)} & {ast_to_latex(cond)}")
        return f"\\begin{{cases}}{' \\\\ '.join(rows)}\\end{{cases}}"
    elif isinstance(node, EquationNode):
        content = ast_to_latex(node.content)
        env = 'equation' if node.number is not None else 'equation*'
        return f"\\begin{{{env}}}{content}\\end{{{env}}}"
    return ''


def gcd(a: int, b: int) -> int:
    a, b = abs(a), abs(b)
    while b:
        a, b = b, a % b
    return a


@dataclass
class SimplificationStep:
    description: str
    before: str
    after: str


class FormulaSimplifier:
    def __init__(self):
        self.steps: List[SimplificationStep] = []

    def simplify(self, formula: str, macro_expander: Optional[MacroExpander] = None) -> List[SimplificationStep]:
        self.steps = []
        current_formula = formula

        if macro_expander:
            current_formula = macro_expander.expand(current_formula)

        self.steps.append(SimplificationStep("原式", current_formula, current_formula))

        try:
            current_formula = self._apply_simplifications(current_formula)
        except Exception:
            pass

        return self.steps

    def _parse_formula(self, formula: str) -> ASTNode:
        tokenizer = Tokenizer(formula)
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)
        return parser.parse()

    def _apply_simplifications(self, formula: str) -> str:
        ast = self._parse_formula(formula)
        simplified = self._simplify_node(ast)
        result = ast_to_latex(simplified)
        if result != formula:
            self.steps.append(SimplificationStep("代数化简", formula, result))
        return result

    def _simplify_node(self, node: ASTNode) -> ASTNode:
        if isinstance(node, BinOpNode):
            left = self._simplify_node(node.left)
            right = self._simplify_node(node.right)
            return self._simplify_binop(left, node.op, right)
        elif isinstance(node, UnaryOpNode):
            operand = self._simplify_node(node.operand)
            return self._simplify_unary(node.op, operand)
        elif isinstance(node, FractionNode):
            num = self._simplify_node(node.numerator)
            den = self._simplify_node(node.denominator)
            return self._simplify_fraction(num, den)
        elif isinstance(node, SuperscriptNode):
            base = self._simplify_node(node.base)
            sup = self._simplify_node(node.sup)
            return self._simplify_superscript(base, sup)
        elif isinstance(node, ExprListNode):
            simplified = [self._simplify_node(item) for item in node.items]
            return ExprListNode(simplified)
        return node

    def _simplify_binop(self, left: ASTNode, op: str, right: ASTNode) -> ASTNode:
        if op == '+':
            if isinstance(left, NumberNode) and left.value == '0':
                self._add_step_if_changed("零元素消除", BinOpNode(left, op, right), right)
                return right
            if isinstance(right, NumberNode) and right.value == '0':
                self._add_step_if_changed("零元素消除", BinOpNode(left, op, right), left)
                return left
            if isinstance(left, NumberNode) and isinstance(right, NumberNode):
                result = str(float(left.value) + float(right.value))
                if result.endswith('.0'):
                    result = result[:-2]
                simplified = NumberNode(result)
                self._add_step_if_changed("常数运算", BinOpNode(left, op, right), simplified)
                return simplified
        elif op == '-':
            if isinstance(right, NumberNode) and right.value == '0':
                self._add_step_if_changed("零元素消除", BinOpNode(left, op, right), left)
                return left
            if isinstance(left, NumberNode) and isinstance(right, NumberNode):
                result = str(float(left.value) - float(right.value))
                if result.endswith('.0'):
                    result = result[:-2]
                simplified = NumberNode(result)
                self._add_step_if_changed("常数运算", BinOpNode(left, op, right), simplified)
                return simplified
        elif op == '*':
            if isinstance(left, NumberNode) and left.value == '1':
                self._add_step_if_changed("单位元素消除", BinOpNode(left, op, right), right)
                return right
            if isinstance(right, NumberNode) and right.value == '1':
                self._add_step_if_changed("单位元素消除", BinOpNode(left, op, right), left)
                return left
            if isinstance(left, NumberNode) and left.value == '0':
                simplified = NumberNode('0')
                self._add_step_if_changed("零元素消除", BinOpNode(left, op, right), simplified)
                return simplified
            if isinstance(right, NumberNode) and right.value == '0':
                simplified = NumberNode('0')
                self._add_step_if_changed("零元素消除", BinOpNode(left, op, right), simplified)
                return simplified
            if isinstance(left, NumberNode) and isinstance(right, NumberNode):
                result = str(float(left.value) * float(right.value))
                if result.endswith('.0'):
                    result = result[:-2]
                simplified = NumberNode(result)
                self._add_step_if_changed("常数运算", BinOpNode(left, op, right), simplified)
                return simplified
        elif op == '/':
            if isinstance(right, NumberNode) and right.value == '1':
                self._add_step_if_changed("单位元素消除", BinOpNode(left, op, right), left)
                return left
        elif op == '^':
            return self._simplify_superscript(left, right)

        return BinOpNode(left, op, right)

    def _simplify_unary(self, op: str, operand: ASTNode) -> ASTNode:
        if op == '-':
            if isinstance(operand, NumberNode):
                if operand.value.startswith('-'):
                    simplified = NumberNode(operand.value[1:])
                    self._add_step_if_changed("负号消除", UnaryOpNode(op, operand), simplified)
                    return simplified
                elif operand.value != '0':
                    simplified = NumberNode('-' + operand.value)
                    self._add_step_if_changed("常数运算", UnaryOpNode(op, operand), simplified)
                    return simplified
        return UnaryOpNode(op, operand)

    def _simplify_fraction(self, num: ASTNode, den: ASTNode) -> ASTNode:
        if isinstance(num, NumberNode) and isinstance(den, NumberNode):
            try:
                num_val = int(num.value)
                den_val = int(den.value)
                if den_val != 0:
                    g = gcd(num_val, den_val)
                    if g > 1:
                        simplified_num = NumberNode(str(num_val // g))
                        simplified_den = NumberNode(str(den_val // g))
                        simplified = FractionNode(simplified_num, simplified_den)
                        self._add_step_if_changed("分数约分", FractionNode(num, den), simplified)
                        return simplified
            except ValueError:
                pass

        if isinstance(den, NumberNode) and den.value == '1':
            self._add_step_if_changed("单位分母消除", FractionNode(num, den), num)
            return num

        if isinstance(num, NumberNode) and num.value == '0':
            simplified = NumberNode('0')
            self._add_step_if_changed("零分子消除", FractionNode(num, den), simplified)
            return simplified

        return FractionNode(num, den)

    def _simplify_superscript(self, base: ASTNode, sup: ASTNode) -> ASTNode:
        if isinstance(sup, NumberNode):
            if sup.value == '0':
                simplified = NumberNode('1')
                self._add_step_if_changed("零次幂", SuperscriptNode(base, sup), simplified)
                return simplified
            if sup.value == '1':
                self._add_step_if_changed("一次幂消除", SuperscriptNode(base, sup), base)
                return base

        if isinstance(base, SuperscriptNode):
            combined_sup = BinOpNode(base.sup, '*', sup)
            if isinstance(base.sup, NumberNode) and isinstance(sup, NumberNode):
                try:
                    result = str(float(base.sup.value) ** float(sup.value))
                    if result.endswith('.0'):
                        result = result[:-2]
                    combined_sup = NumberNode(result)
                except ValueError:
                    pass
            simplified = SuperscriptNode(base.base, combined_sup)
            self._add_step_if_changed("幂运算合并", SuperscriptNode(base, sup), simplified)
            return simplified

        return SuperscriptNode(base, sup)

    def _add_step_if_changed(self, desc: str, before: ASTNode, after: ASTNode):
        before_latex = ast_to_latex(before)
        after_latex = ast_to_latex(after)
        if before_latex != after_latex:
            self.steps.append(SimplificationStep(desc, before_latex, after_latex))


def render_simplification_chain(steps: List[SimplificationStep], unicode_mode: bool = False) -> str:
    """渲染化简步骤链"""
    if not steps:
        return ""

    rendered_steps = []
    max_width = 0

    for i, step in enumerate(steps):
        before = render_latex(step.before, unicode_mode)
        after = render_latex(step.after, unicode_mode)

        before_lines = before.split('\n')
        after_lines = after.split('\n')
        step_height = max(len(before_lines), len(after_lines))

        arrow_lines = [' ' * 3 + '→' + ' ' * 3] * step_height if i < len(steps) - 1 else [''] * step_height
        if i == 0:
            arrow_lines = [''] * step_height

        header = f"  [{step.description}]"
        combined = []
        combined.append(header)
        for j in range(step_height):
            b = before_lines[j] if j < len(before_lines) else ' ' * len(before_lines[0])
            a = after_lines[j] if j < len(after_lines) else ' ' * len(after_lines[0])
            arr = arrow_lines[j] if j < len(arrow_lines) else ' ' * 7
            combined.append(f"  {b}{arr}{a}")

        rendered_steps.append('\n'.join(combined))

    return '\n\n'.join(rendered_steps)


# =====================================================================
# 公式对比与差异高亮 (Formula Diff)
# =====================================================================

@dataclass
class DiffSegment:
    text: str
    changed: bool
    left_only: bool = False
    right_only: bool = False


def compute_diff(left: str, right: str) -> Tuple[List[DiffSegment], List[DiffSegment]]:
    """计算两个字符串的逐字符差异"""
    matcher = difflib.SequenceMatcher(None, left, right)
    left_segments: List[DiffSegment] = []
    right_segments: List[DiffSegment] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            segment = left[i1:i2]
            left_segments.append(DiffSegment(segment, False))
            right_segments.append(DiffSegment(segment, False))
        elif tag == 'replace':
            left_segments.append(DiffSegment(left[i1:i2], True, left_only=True))
            right_segments.append(DiffSegment(right[j1:j2], True, right_only=True))
        elif tag == 'delete':
            left_segments.append(DiffSegment(left[i1:i2], True, left_only=True))
            right_segments.append(DiffSegment('', True, right_only=True))
        elif tag == 'insert':
            left_segments.append(DiffSegment('', True, left_only=True))
            right_segments.append(DiffSegment(right[j1:j2], True, right_only=True))

    return left_segments, right_segments


def highlight_diff(segments: List[DiffSegment], use_color: bool = True) -> str:
    """为差异片段添加高亮标记"""
    result = []
    for seg in segments:
        if not seg.text:
            continue
        if seg.changed:
            if use_color:
                if seg.left_only:
                    result.append(f"\033[91m[{seg.text}]\033[0m")
                elif seg.right_only:
                    result.append(f"\033[92m[{seg.text}]\033[0m")
                else:
                    result.append(f"\033[93m[{seg.text}]\033[0m")
            else:
                result.append(f"[{seg.text}]")
        else:
            result.append(seg.text)
    return ''.join(result)


def render_formula_diff(left_formula: str, right_formula: str, unicode_mode: bool = False, use_color: bool = True) -> str:
    """并排渲染两个公式并高亮差异"""
    left_rendered = render_latex(left_formula, unicode_mode)
    right_rendered = render_latex(right_formula, unicode_mode)

    left_lines = left_rendered.split('\n')
    right_lines = right_rendered.split('\n')

    max_height = max(len(left_lines), len(right_lines))
    left_width = max(len(line) for line in left_lines) if left_lines else 0
    right_width = max(len(line) for line in right_lines) if right_lines else 0

    left_segments, right_segments = compute_diff(left_formula, right_formula)
    left_highlighted = highlight_diff(left_segments, use_color)
    right_highlighted = highlight_diff(right_segments, use_color)

    result = []
    result.append(f"公式 A: {left_highlighted}")
    result.append(f"公式 B: {right_highlighted}")
    result.append("")
    result.append(f"{'渲染 A':^{left_width}}{'   '}{'渲染 B':^{right_width}}")
    result.append(f"{'─' * left_width}{'   '}{'─' * right_width}")

    for i in range(max_height):
        left_line = left_lines[i] if i < len(left_lines) else ' ' * left_width
        right_line = right_lines[i] if i < len(right_lines) else ' ' * right_width
        left_padded = left_line.ljust(left_width)
        right_padded = right_line.ljust(right_width)

        arrow = '   '
        if i == max_height // 2:
            arrow = ' → '

        result.append(f"{left_padded}{arrow}{right_padded}")

    return '\n'.join(result)


# =====================================================================
# 渲染质量增强 (Rendering Quality Enhancements)
# =====================================================================

def wrap_text(text: str, max_width: int) -> List[str]:
    """将文本按最大宽度折行"""
    if max_width <= 0:
        return [text]
    lines = []
    current = text
    while len(current) > max_width:
        break_pos = max_width
        for i in range(max_width, max(0, max_width - 20), -1):
            if current[i] in ' +-*/=<>':
                break_pos = i + 1
                break
        lines.append(current[:break_pos])
        current = current[break_pos:]
    if current:
        lines.append(current)
    return lines


def box_wrap(box: Box, max_width: int) -> Box:
    """对Box进行折行处理"""
    if max_width <= 0 or box.width <= max_width:
        return box

    new_lines = []
    for line in box.lines:
        wrapped = wrap_text(line, max_width)
        new_lines.extend(wrapped)

    return Box.from_lines(new_lines, baseline=min(box.baseline, len(new_lines) - 1))


def render_latex(formula: str, unicode_mode: bool = False, max_width: int = 0,
                 macro_expander: Optional[MacroExpander] = None) -> str:
    """将LaTeX公式渲染为ASCII Art字符串"""
    try:
        processed = formula
        if macro_expander:
            processed = macro_expander.expand(processed)

        tokenizer = Tokenizer(processed)
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        box = ast.render(unicode_mode)

        if max_width > 0:
            box = box_wrap(box, max_width)

        return '\n'.join(box.lines)
    except Exception as e:
        return f"[渲染错误: {e}]"


# =====================================================================
# 预置示例公式
# =====================================================================

EXAMPLES = [
    ("二次方程求根公式", r"x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}"),
    ("欧拉公式", r"e^{i\pi} + 1 = 0"),
    ("矩阵乘法", r"\begin{bmatrix} a & b \\ c & d \end{bmatrix} \begin{bmatrix} x \\ y \end{bmatrix} = \begin{bmatrix} ax+by \\ cx+dy \end{bmatrix}"),
    ("2x2行列式", r"\det\begin{bmatrix} a & b \\ c & d \end{bmatrix} = ad - bc"),
    ("定积分", r"\int_{a}^{b} x^2 dx = \frac{b^3 - a^3}{3}"),
    ("级数求和", r"\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}"),
    ("二次方程一般式", r"ax^2 + bx + c = 0"),
    ("麦克斯韦方程(简化)", r"\nabla \cdot \mathbf{E} = \frac{\rho}{\epsilon_0}"),
    ("带分数的矩阵", r"\begin{bmatrix} \frac{1}{2} & \frac{1}{3} \\ \frac{1}{4} & \frac{1}{5} \end{bmatrix}"),
    ("复合表达式", r"\frac{\sum_{i=1}^{n} x_i}{\sqrt{n}}"),
]


# =====================================================================
# CLI 接口
# =====================================================================

def interactive_mode(unicode_mode: bool = False, macros_file: Optional[str] = None, max_width: int = 0):
    """交互式REPL模式"""
    macro_expander = MacroExpander()
    if macros_file:
        macro_expander.load_from_file(macros_file)

    print("╔══════════════════════════════════════════╗")
    print("║  LaTeX -> ASCII Art 渲染器 (交互式模式)  ║")
    print("║  输入公式回车渲染，输入 quit 退出         ║")
    print("╚══════════════════════════════════════════╝")
    print()

    while True:
        try:
            formula = input("LaTeX> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not formula:
            continue
        if formula.lower() in ('quit', 'exit', 'q'):
            break
        if formula.lower() == 'help':
            print("输入LaTeX公式，如: \\frac{a}{b}, x^2, \\sqrt{x}, \\sum, \\int, 矩阵等")
            print("支持 \\newcommand 定义宏，如: \\newcommand{\\deriv}[2]{\\frac{d#1}{d#2}}")
            print("输入 quit 退出")
            continue
        if formula.lower() == 'examples':
            for name, ex in EXAMPLES:
                print(f"\n=== {name} ===")
                print(f"LaTeX: {ex}")
                print(render_latex(ex, unicode_mode, max_width, macro_expander))
            continue
        if formula.lower() == 'demo':
            run_demo(unicode_mode, max_width, macro_expander)
            continue

        try:
            result = render_latex(formula, unicode_mode, max_width, macro_expander)
            print()
            print(result)
            print()
        except Exception as e:
            print(f"\n[错误: {e}]\n")


def render_file(input_file: str, output_file: Optional[str] = None, unicode_mode: bool = False,
                macros_file: Optional[str] = None, max_width: int = 0):
    """从文件读取公式并渲染"""
    macro_expander = MacroExpander()
    if macros_file:
        macro_expander.load_from_file(macros_file)

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"读取文件失败: {e}", file=sys.stderr)
        return

    formulas = []
    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '||' in line:
            name, formula = line.split('||', 1)
            formulas.append((name.strip(), formula.strip()))
        else:
            formulas.append((f"公式{len(formulas) + 1}", line))

    results = []
    for name, formula in formulas:
        rendered = render_latex(formula, unicode_mode, max_width, macro_expander)
        results.append(f"=== {name} ===\nLaTeX: {formula}\n{rendered}\n")

    output = '\n'.join(results)

    if output_file:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(output)
            print(f"已导出到 {output_file}")
        except Exception as e:
            print(f"写入文件失败: {e}", file=sys.stderr)
    else:
        print(output)


def run_demo(unicode_mode: bool = False, max_width: int = 0, macro_expander: Optional[MacroExpander] = None):
    """运行所有预置示例"""
    print("\n" + "=" * 60)
    print("  LaTeX ASCII Art 渲染器 - 预置示例演示")
    print("=" * 60)

    for name, formula in EXAMPLES:
        print(f"\n{'─' * 60}")
        print(f"▶ {name}")
        print(f"  LaTeX: {formula}")
        print(f"{'─' * 60}")
        result = render_latex(formula, unicode_mode, max_width, macro_expander)
        print(result)
        print()


def diff_command(formula1: str, formula2: str, unicode_mode: bool = False, max_width: int = 0,
                 macros_file: Optional[str] = None, no_color: bool = False,
                 output_file: Optional[str] = None):
    """对比两个公式并高亮差异"""
    macro_expander = MacroExpander()
    if macros_file:
        macro_expander.load_from_file(macros_file)

    result = render_formula_diff(formula1, formula2, unicode_mode, not no_color)
    if max_width > 0:
        lines = result.split('\n')
        wrapped_lines = []
        for line in lines:
            wrapped_lines.extend(wrap_text(line, max_width))
        result = '\n'.join(wrapped_lines)

    if output_file:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(result + '\n')
            print(f"已导出到 {output_file}")
        except Exception as e:
            print(f"写入文件失败: {e}", file=sys.stderr)
    else:
        print(result)


def simplify_command(formula: str, unicode_mode: bool = False, max_width: int = 0,
                     macros_file: Optional[str] = None, output_file: Optional[str] = None):
    """化简公式并显示步骤"""
    macro_expander = MacroExpander()
    if macros_file:
        macro_expander.load_from_file(macros_file)

    simplifier = FormulaSimplifier()
    steps = simplifier.simplify(formula, macro_expander)
    result = render_simplification_chain(steps, unicode_mode)

    if max_width > 0:
        lines = result.split('\n')
        wrapped_lines = []
        for line in lines:
            wrapped_lines.extend(wrap_text(line, max_width))
        result = '\n'.join(wrapped_lines)

    if output_file:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(result + '\n')
            print(f"已导出到 {output_file}")
        except Exception as e:
            print(f"写入文件失败: {e}", file=sys.stderr)
    else:
        print(result)


def main():
    parser = argparse.ArgumentParser(
        description='LaTeX数学公式到终端ASCII Art渲染器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python texrender.py render "\\\\frac{a}{b}"
  python texrender.py render --unicode "x^2 + y^2 = z^2"
  python texrender.py render "\\\\frac{2x}{4}" --width 40
  python texrender.py interactive
  python texrender.py interactive --macros macros.txt
  python texrender.py file formulas.txt
  python texrender.py file formulas.txt -o output.txt
  python texrender.py diff "\\\\frac{a}{b}" "\\\\frac{c}{d}"
  python texrender.py simplify "\\\\frac{2x}{4}"
  python texrender.py simplify "\\\\frac{6}{9} + \\\\frac{2}{4}"
  python texrender.py demo
  python texrender.py examples
        """
    )
    parser.add_argument('--macros', help='宏定义文件路径（每行一个\\newcommand定义）')
    parser.add_argument('--width', type=int, default=0, help='输出最大宽度，超宽自动折行')
    parser.add_argument('--unicode', '-u', action='store_true', help='使用Unicode符号增强显示')

    subparsers = parser.add_subparsers(dest='command', help='命令')

    render_parser = subparsers.add_parser('render', help='渲染单个LaTeX公式')
    render_parser.add_argument('formula', help='LaTeX公式字符串')
    render_parser.add_argument('--unicode', '-u', action='store_true', help='使用Unicode符号增强显示')
    render_parser.add_argument('--output', '-o', help='输出到文件')
    render_parser.add_argument('--macros', help='宏定义文件路径')
    render_parser.add_argument('--width', type=int, default=0, help='输出最大宽度')

    diff_parser = subparsers.add_parser('diff', help='对比两个LaTeX公式并高亮差异')
    diff_parser.add_argument('formula1', help='第一个LaTeX公式字符串')
    diff_parser.add_argument('formula2', help='第二个LaTeX公式字符串')
    diff_parser.add_argument('--unicode', '-u', action='store_true', help='使用Unicode符号增强显示')
    diff_parser.add_argument('--output', '-o', help='输出到文件')
    diff_parser.add_argument('--macros', help='宏定义文件路径')
    diff_parser.add_argument('--width', type=int, default=0, help='输出最大宽度')
    diff_parser.add_argument('--no-color', action='store_true', help='禁用ANSI颜色，使用方括号标注')

    simplify_parser = subparsers.add_parser('simplify', help='化简LaTeX公式并显示步骤')
    simplify_parser.add_argument('formula', help='LaTeX公式字符串')
    simplify_parser.add_argument('--unicode', '-u', action='store_true', help='使用Unicode符号增强显示')
    simplify_parser.add_argument('--output', '-o', help='输出到文件')
    simplify_parser.add_argument('--macros', help='宏定义文件路径')
    simplify_parser.add_argument('--width', type=int, default=0, help='输出最大宽度')

    file_parser = subparsers.add_parser('file', help='从文件批量渲染公式')
    file_parser.add_argument('input', help='输入文件路径（每行一个公式，#开头为注释）')
    file_parser.add_argument('--output', '-o', help='输出文件路径')
    file_parser.add_argument('--unicode', '-u', action='store_true', help='使用Unicode符号增强显示')
    file_parser.add_argument('--macros', help='宏定义文件路径')
    file_parser.add_argument('--width', type=int, default=0, help='输出最大宽度')

    interactive_parser = subparsers.add_parser('interactive', help='交互式REPL模式')
    interactive_parser.add_argument('--unicode', '-u', action='store_true', help='使用Unicode符号增强显示')
    interactive_parser.add_argument('--macros', help='宏定义文件路径')
    interactive_parser.add_argument('--width', type=int, default=0, help='输出最大宽度')

    demo_parser = subparsers.add_parser('demo', help='运行所有预置示例')
    demo_parser.add_argument('--unicode', '-u', action='store_true', help='使用Unicode符号增强显示')
    demo_parser.add_argument('--macros', help='宏定义文件路径')
    demo_parser.add_argument('--width', type=int, default=0, help='输出最大宽度')

    subparsers.add_parser('examples', help='列出所有预置示例公式')

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    unicode_mode = getattr(args, 'unicode', False)
    macros_file = getattr(args, 'macros', None)
    max_width = getattr(args, 'width', 0)

    if args.command == 'render':
        macro_expander = MacroExpander()
        if args.macros:
            macro_expander.load_from_file(args.macros)
        result = render_latex(args.formula, unicode_mode, args.width, macro_expander)
        if args.output:
            try:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(result + '\n')
                print(f"已导出到 {args.output}")
            except Exception as e:
                print(f"写入文件失败: {e}", file=sys.stderr)
        else:
            print(result)

    elif args.command == 'diff':
        diff_command(args.formula1, args.formula2, unicode_mode, args.width,
                     args.macros, args.no_color, args.output)

    elif args.command == 'simplify':
        simplify_command(args.formula, unicode_mode, args.width, args.macros, args.output)

    elif args.command == 'file':
        render_file(args.input, args.output, unicode_mode, args.macros, args.width)

    elif args.command == 'interactive':
        interactive_mode(unicode_mode, args.macros, args.width)

    elif args.command == 'demo':
        macro_expander = MacroExpander()
        if args.macros:
            macro_expander.load_from_file(args.macros)
        run_demo(unicode_mode, args.width, macro_expander)

    elif args.command == 'examples':
        print("预置示例公式:")
        print()
        for i, (name, formula) in enumerate(EXAMPLES, 1):
            print(f"  {i}. {name}")
            print(f"     {formula}")
            print()


if __name__ == '__main__':
    main()
