from __future__ import annotations

import ast
import operator
from pathlib import Path
from typing import Any
from uuid import UUID

from .capability_forge import (
    ActionContext,
    ActionUnit,
    CapabilityForge,
    RiskLevel,
    action_contract,
)

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


@action_contract(
    name="calculate",
    description="Evaluate a finite arithmetic expression without executing code.",
    input_contract={
        "type": "object",
        "properties": {"expression": {"type": "string", "minLength": 1, "maxLength": 200}},
        "required": ["expression"],
        "additionalProperties": False,
    },
    output_contract={
        "type": "object",
        "properties": {"value": {"type": "number"}},
        "required": ["value"],
        "additionalProperties": False,
    },
)
def calculate(arguments: dict[str, Any], _context: ActionContext) -> dict[str, float | int]:
    tree = ast.parse(arguments["expression"], mode="eval")
    return {"value": _evaluate_node(tree.body)}


@action_contract(
    name="read_workspace_text",
    description="Read a UTF-8 text file located inside the configured workspace.",
    input_contract={
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1},
            "max_characters": {"type": "integer", "minimum": 1, "maximum": 100000},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    output_contract={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "truncated": {"type": "boolean"},
        },
        "required": ["path", "content", "truncated"],
        "additionalProperties": False,
    },
)
def read_workspace_text(arguments: dict[str, Any], context: ActionContext) -> dict[str, Any]:
    target = _workspace_path(context, arguments["path"])
    max_characters = arguments.get("max_characters", 20_000)
    content = target.read_text(encoding="utf-8")
    return {
        "path": target.relative_to(context.root_path.resolve()).as_posix(),
        "content": content[:max_characters],
        "truncated": len(content) > max_characters,
    }


@action_contract(
    name="write_workspace_text",
    description="Write UTF-8 text to a file inside the configured workspace.",
    input_contract={
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
    output_contract={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "characters": {"type": "integer"},
        },
        "required": ["path", "characters"],
        "additionalProperties": False,
    },
    risk_level=RiskLevel.WRITE,
)
def write_workspace_text(arguments: dict[str, Any], context: ActionContext) -> dict[str, Any]:
    target = _workspace_path(context, arguments["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(arguments["content"], encoding="utf-8")
    return {
        "path": target.relative_to(context.root_path.resolve()).as_posix(),
        "characters": len(arguments["content"]),
    }


BUILTIN_ACTIONS: tuple[ActionUnit, ...] = (
    calculate,
    read_workspace_text,
    write_workspace_text,
)


def register_builtin_actions(forge: CapabilityForge, workspace_id: UUID) -> None:
    for action in BUILTIN_ACTIONS:
        forge.register(workspace_id, action)


def _workspace_path(context: ActionContext, requested_path: str) -> Path:
    if context.root_path is None:
        raise ValueError("this action requires a configured workspace root")
    root = context.root_path.resolve()
    target = (root / requested_path).resolve()
    if target != root and root not in target.parents:
        raise ValueError("path escapes the configured workspace")
    return target


def _evaluate_node(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 12:
            raise ValueError("exponent exceeds the calculation limit")
        value = _BINARY_OPERATORS[type(node.op)](left, right)
        if abs(value) > 1e100:
            raise ValueError("calculation exceeds the magnitude limit")
        return value
    raise ValueError("expression contains an unsupported operation")
