"""
Code execution endpoint -- run Python and JavaScript safely.
"""
from __future__ import annotations

import asyncio
import tempfile
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.models.user import User
from app.api.v1.endpoints.auth import get_current_active_user

router = APIRouter()


class CodeExecutionRequest(BaseModel):
    language: str = Field(..., pattern="^(python|javascript)$")
    code: str = Field(..., min_length=1, max_length=10000)


class CodeExecutionResponse(BaseModel):
    output: str = ""
    error: Optional[str] = None
    execution_time: float = 0.0
    language: str = ""


BLOCKED_PYTHON_IMPORTS = {
    "os", "sys", "subprocess", "shutil", "pathlib",
    "socket", "http", "urllib", "requests", "httpx",
    "ctypes", "signal", "multiprocessing", "threading",
    "importlib", "builtins", "code", "codeop",
}

BLOCKED_PYTHON_BUILTINS = {
    "exec", "eval", "compile", "__import__", "open", "input",
    "globals", "locals", "breakpoint",
}


def _validate_python_code(code: str) -> None:
    """AST-based validation — catches obfuscated bypass attempts."""
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"Syntax error: {e}")

    for node in ast.walk(tree):
        # Block dangerous imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod in BLOCKED_PYTHON_IMPORTS:
                    raise ValueError(f"Import '{mod}' is not allowed.")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod = node.module.split(".")[0]
                if mod in BLOCKED_PYTHON_IMPORTS:
                    raise ValueError(f"Import '{mod}' is not allowed.")
        # Block dangerous builtins via attribute access (e.g. __import__)
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                raise ValueError(f"Access to dunder attribute '{node.attr}' is not allowed.")
        # Block dangerous function calls
        elif isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name in BLOCKED_PYTHON_BUILTINS:
                raise ValueError(f"Function '{func_name}' is not allowed.")
        # Block eval/exec/compile as names
        elif isinstance(node, ast.Name) and node.id in BLOCKED_PYTHON_BUILTINS:
            raise ValueError(f"Function '{node.id}' is not allowed.")
        # Block __import__ as expression
        elif isinstance(node, ast.Name) and node.id.startswith("__") and node.id.endswith("__"):
            raise ValueError(f"Access to dunder name '{node.id}' is not allowed.")


async def _run_python(code: str) -> tuple:
    start = time.time()
    try:
        _validate_python_code(code)
    except ValueError as e:
        return "", str(e), time.time() - start

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        tmp_path = f.name

    try:
        proc = await asyncio.create_subprocess_exec(
            settings.PYTHON_EXECUTABLE or "python3",
            tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        elapsed = time.time() - start
        output = stdout.decode("utf-8", errors="replace").strip()
        error = stderr.decode("utf-8", errors="replace").strip()
        return output, error if error else None, elapsed
    except asyncio.TimeoutError:
        return "", "Execution timed out (10s limit)", time.time() - start
    except FileNotFoundError:
        return "", "Python interpreter not found", time.time() - start
    finally:
        import os
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


async def _run_javascript(code: str) -> tuple:
    start = time.time()
    dangerous = ["require('fs')", "require('child_process')", "process.exit", "require('net')", "require('http')"]
    for d in dangerous:
        if d in code:
            return "", "Pattern '" + d + "' is not allowed.", time.time() - start

    NL = chr(10)  # literal newline character for JS
    wrapper_lines = [
        "var _output = [];",
        "var _origLog = console.log;",
        "console.log = function() { for(var i=0;i<arguments.length;i++) _output.push(String(arguments[i])); };",
        "console.error = function() { for(var i=0;i<arguments.length;i++) _output.push('[ERROR] '+String(arguments[i])); };",
        "try {",
        code,
        "} catch(e) { _output.push('[ERROR] ' + e.message); }",
        "process.stdout.write(_output.join('" + chr(92) + "n'));",
    ]
    wrapped = NL.join(wrapper_lines)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(wrapped)
        tmp_path = f.name

    try:
        proc = await asyncio.create_subprocess_exec(
            "node", tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        elapsed = time.time() - start
        output = stdout.decode("utf-8", errors="replace").strip()
        error = stderr.decode("utf-8", errors="replace").strip()
        return output, error if error else None, elapsed
    except asyncio.TimeoutError:
        return "", "Execution timed out (10s limit)", time.time() - start
    except FileNotFoundError:
        return "", "Node.js not found", time.time() - start
    finally:
        import os
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post("/run", response_model=CodeExecutionResponse)
async def run_code(
    request: CodeExecutionRequest,
    current_user: User = Depends(get_current_active_user),
):
    if request.language == "python":
        output, error, elapsed = await _run_python(request.code)
    elif request.language == "javascript":
        output, error, elapsed = await _run_javascript(request.code)
    else:
        raise HTTPException(status_code=400, detail="Language not supported")

    return CodeExecutionResponse(
        output=output, error=error, execution_time=round(elapsed, 3), language=request.language,
    )
