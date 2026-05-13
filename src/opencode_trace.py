import os
import subprocess
import threading
from dataclasses import dataclass

from config import TRACE_ON
from .trace_writer import (
    new_event_id,
    record_trace_event,
    utc_now_iso,
    write_json_payload,
    write_payload,
)


def function_id_from_extracted_path(path):
    rel = path.replace("\\", "/")
    for prefix in ("fm_agent/extracted_functions/", "extracted_functions/"):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    return os.path.splitext(rel)[0].replace("/", "::")


def function_id_from_result_path(path):
    rel = path.replace("\\", "/")
    prefix = "fm_agent/logic_verification_results/"
    if rel.startswith(prefix):
        rel = rel[len(prefix):]
    return os.path.splitext(rel)[0].replace("/", "::")


@dataclass
class TracedOpenCodeProcess:
    proc: subprocess.Popen
    work_dir: str
    event_id: str
    stage: str
    started: str
    command: list
    prompt: str
    workflow_file: str | None = None
    batch_prompt_file: str | None = None
    function_ids: list | None = None
    input_files: list | None = None
    output_files: list | None = None
    summary: str | None = None
    metadata: dict | None = None
    log_path: str | None = None
    log_thread: threading.Thread | None = None


def _trace_dir(work_dir):
    return os.path.join(work_dir, "trace")


def _payload_dir(trace_dir):
    path = os.path.join(trace_dir, "payloads")
    os.makedirs(path, exist_ok=True)
    return path


def _payload_ref(trace_dir, path):
    return os.path.relpath(path, os.path.dirname(trace_dir))


def _opencode_log_path(work_dir, event_id):
    return os.path.join(_payload_dir(_trace_dir(work_dir)), f"{event_id}_opencode.log")


def _read_text_if_exists(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _artifact_item(trace_dir, event_id, item_type, label, path, payload_name):
    item = {"type": item_type, "label": label, "path": path}
    content = _read_text_if_exists(path) if path else None
    if content is not None:
        item["content_ref"] = write_payload(trace_dir, event_id, payload_name, content)
    return item


def _copy_opencode_output(stream, log_file, trace_log_path=None):
    trace_log = None
    try:
        if trace_log_path:
            trace_log = open(trace_log_path, "w", encoding="utf-8", errors="replace")
        for chunk in iter(lambda: stream.read(4096), ""):
            if not chunk:
                break
            log_file.write(chunk)
            log_file.flush()
            if trace_log:
                trace_log.write(chunk)
                trace_log.flush()
    finally:
        if trace_log:
            trace_log.close()
    stream.close()


def _start_opencode_process(proj_dir, command, log_file, trace_log_path):
    proc = subprocess.Popen(
        command,
        cwd=proj_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    log_thread = threading.Thread(
        target=_copy_opencode_output,
        args=(proc.stdout, log_file, trace_log_path),
        daemon=True,
    )
    log_thread.start()
    return proc, log_thread


def record_opencode_call(
    work_dir,
    event_id,
    stage,
    status,
    started,
    ended,
    command,
    prompt,
    workflow_file=None,
    batch_prompt_file=None,
    function_ids=None,
    input_files=None,
    output_files=None,
    exit_code=None,
    summary=None,
    error=None,
    metadata=None,
    extra_artifacts=None,
    opencode_log_path=None,
):
    if not TRACE_ON:
        return

    trace_dir = _trace_dir(work_dir)
    children = [
        {
            "type": "tool_call",
            "tool": "opencode",
            "content_ref": write_json_payload(trace_dir, event_id, "command.json", command),
        },
        {
            "type": "user_prompt",
            "content_ref": write_payload(trace_dir, event_id, "prompt.txt", prompt),
        },
    ]

    if batch_prompt_file:
        children.append(
            _artifact_item(trace_dir, event_id, "artifact", "batch_prompt", batch_prompt_file, "batch_prompt.md")
        )
    if opencode_log_path and os.path.exists(opencode_log_path):
        children.append(
            {
                "type": "tool_output",
                "label": "opencode-stdout",
                "path": opencode_log_path,
                "content_ref": _payload_ref(trace_dir, opencode_log_path),
            }
        )
    for artifact in extra_artifacts or []:
        children.append(
            _artifact_item(
                trace_dir,
                event_id,
                "artifact",
                artifact.get("label", "artifact"),
                artifact.get("path"),
                artifact.get("payload_name", "artifact.txt"),
            )
        )

    record_trace_event(trace_dir, {
        "event_id": event_id,
        "type": "opencode_call",
        "stage": stage,
        "status": status,
        "start_time": started,
        "end_time": ended,
        "summary": summary or f"OpenCode {stage}",
        "function_ids": function_ids or [],
        "children": children,
        "metadata": {
            "command": command,
            "exit_code": exit_code,
            "input_files": input_files or [],
            "output_files": output_files or [],
            "error": error,
            **(metadata or {}),
        },
    })


def run_opencode_traced(
    proj_dir,
    work_dir,
    command,
    prompt,
    stage,
    log_file,
    workflow_file=None,
    batch_prompt_file=None,
    function_ids=None,
    input_files=None,
    output_files=None,
    summary=None,
    metadata=None,
    extra_artifacts=None,
):
    event_id = new_event_id("opencode")
    started = utc_now_iso()
    exit_code = 0
    error = None
    opencode_log_path = _opencode_log_path(work_dir, event_id) if TRACE_ON else None
    log_thread = None
    try:
        proc, log_thread = _start_opencode_process(proj_dir, command, log_file, opencode_log_path)
        exit_code = proc.wait()
        if log_thread:
            log_thread.join()
        if exit_code != 0:
            raise subprocess.CalledProcessError(exit_code, command)
        return subprocess.CompletedProcess(command, exit_code)
    except subprocess.CalledProcessError as exc:
        exit_code = exc.returncode
        error = str(exc)
        raise
    finally:
        if log_thread and log_thread.is_alive():
            log_thread.join()
        if TRACE_ON:
            record_opencode_call(
                work_dir=work_dir,
                event_id=event_id,
                stage=stage,
                status="success" if exit_code == 0 else "error",
                started=started,
                ended=utc_now_iso(),
                command=command,
                prompt=prompt,
                workflow_file=workflow_file,
                batch_prompt_file=batch_prompt_file,
                function_ids=function_ids,
                input_files=input_files,
                output_files=output_files,
                exit_code=exit_code,
                summary=summary,
                error=error,
                metadata=metadata,
                extra_artifacts=extra_artifacts,
                opencode_log_path=opencode_log_path,
            )


def start_opencode_traced(
    proj_dir,
    work_dir,
    command,
    prompt,
    stage,
    log_file,
    workflow_file=None,
    batch_prompt_file=None,
    function_ids=None,
    input_files=None,
    output_files=None,
    summary=None,
    metadata=None,
):
    event_id = new_event_id("opencode")
    started = utc_now_iso()
    opencode_log_path = _opencode_log_path(work_dir, event_id) if TRACE_ON else None
    proc, log_thread = _start_opencode_process(proj_dir, command, log_file, opencode_log_path)
    return TracedOpenCodeProcess(
        proc=proc,
        work_dir=work_dir,
        event_id=event_id,
        stage=stage,
        started=started,
        command=command,
        prompt=prompt,
        workflow_file=workflow_file,
        batch_prompt_file=batch_prompt_file,
        function_ids=function_ids,
        input_files=input_files,
        output_files=output_files,
        summary=summary,
        metadata=metadata,
        log_path=opencode_log_path,
        log_thread=log_thread,
    )


def finish_opencode_trace(record):
    if record.log_thread:
        record.log_thread.join()
    if TRACE_ON:
        record_opencode_call(
            work_dir=record.work_dir,
            event_id=record.event_id,
            stage=record.stage,
            status="success" if record.proc.returncode == 0 else "error",
            started=record.started,
            ended=utc_now_iso(),
            command=record.command,
            prompt=record.prompt,
            workflow_file=record.workflow_file,
            batch_prompt_file=record.batch_prompt_file,
            function_ids=record.function_ids,
            input_files=record.input_files,
            output_files=record.output_files,
            exit_code=record.proc.returncode,
            summary=record.summary,
            metadata=record.metadata,
            opencode_log_path=record.log_path,
        )
