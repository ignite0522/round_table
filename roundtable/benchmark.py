"""TSec Benchmark Platform client.

只依赖标准库,供 round_table 命令行和 GUI 复用。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, build_opener


DEFAULT_TIMEOUT_S = 15.0


class BenchmarkAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        detail: Any = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.detail = detail


@dataclass(slots=True)
class ChallengeInfo:
    unique_code: str
    description: str | None
    difficulty: str | None
    level: int | None
    total_score: int | None
    flag_count: int | None
    correct_flag_count: int | None
    is_completed: bool
    container_status: str | None
    container_addr: list[str]

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "ChallengeInfo":
        return cls(
            unique_code=str(payload.get("unique_code", "")),
            description=payload.get("description"),
            difficulty=payload.get("difficulty"),
            level=payload.get("level"),
            total_score=payload.get("total_score"),
            flag_count=payload.get("flag_count"),
            correct_flag_count=payload.get("correct_flag_count"),
            is_completed=bool(payload.get("is_completed")),
            container_status=payload.get("container_status"),
            container_addr=[str(x) for x in (payload.get("container_addr") or [])],
        )


@dataclass(slots=True)
class SubmitResult:
    correct: bool
    awarded: int
    cumulative_score: int
    correct_flag_count: int
    total_flag_count: int
    matched_flag_index: int | None
    duplicate: bool = False


def load_benchmark_config(
    *,
    base_url: str | None = None,
    token: str | None = None,
) -> tuple[str | None, str | None]:
    return (
        base_url or os.getenv("BENCHMARK_BASE_URL"),
        token or os.getenv("BENCHMARK_TOKEN"),
    )


class BenchmarkClient:
    def __init__(self, base_url: str, token: str, *, timeout_s: float = DEFAULT_TIMEOUT_S):
        if not base_url or not token:
            raise ValueError("benchmark base_url/token 不能为空")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s
        self._opener = build_opener()

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        if query:
            url = f"{url}?{urlencode(query)}"
        body = None
        headers = {
            "Accept": "application/json",
            "BENCHMARK_TOKEN": self.token,
        }
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(url, data=body, headers=headers, method=method.upper())
        try:
            with self._opener.open(req, timeout=self.timeout_s) as resp:
                raw = resp.read()
                if not raw:
                    return None
                text = raw.decode("utf-8", "replace")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        except HTTPError as e:
            raw = e.read()
            text = raw.decode("utf-8", "replace") if raw else ""
            code = None
            detail = None
            message = text or f"HTTP {e.code}"
            try:
                payload = json.loads(text)
                code = payload.get("code")
                detail = payload.get("detail")
                message = payload.get("message") or message
            except Exception:
                pass
            raise BenchmarkAPIError(message, status=e.code, code=code, detail=detail) from e
        except URLError as e:
            raise BenchmarkAPIError(f"网络错误: {e.reason}") from e

    def list_challenges(self) -> list[ChallengeInfo]:
        payload = self._request("GET", "/openapi/v1/challenges")
        return [ChallengeInfo.from_json(item) for item in payload or []]

    def get_challenge(self, unique_code: str) -> ChallengeInfo:
        for item in self.list_challenges():
            if item.unique_code == unique_code:
                return item
        raise BenchmarkAPIError(
            f"题目不存在: {unique_code}",
            status=404,
            code="challenge_not_found",
        )

    def start_challenge(self, unique_code: str) -> list[str]:
        payload = self._request(
            "POST",
            "/openapi/v1/challenges/start",
            query={"unique_code": unique_code},
        )
        return [str(x) for x in (payload or {}).get("container_addr", [])]

    def get_hint(self, unique_code: str) -> str | None:
        payload = self._request(
            "GET",
            "/openapi/v1/challenges/hint",
            query={"unique_code": unique_code},
        )
        return (payload or {}).get("hint")

    def submit_flag(self, unique_code: str, flag: str) -> SubmitResult:
        try:
            payload = self._request(
                "POST",
                "/openapi/v1/challenges/submit",
                json_body={"unique_code": unique_code, "flag": flag},
            ) or {}
            return SubmitResult(
                correct=bool(payload.get("correct")),
                awarded=int(payload.get("awarded") or 0),
                cumulative_score=int(payload.get("cumulative_score") or 0),
                correct_flag_count=int(payload.get("correct_flag_count") or 0),
                total_flag_count=int(payload.get("total_flag_count") or 0),
                matched_flag_index=payload.get("matched_flag_index"),
                duplicate=False,
            )
        except BenchmarkAPIError as e:
            if e.code == "duplicate":
                challenge = None
                try:
                    challenge = self.get_challenge(unique_code)
                except Exception:
                    challenge = None
                return SubmitResult(
                    correct=True,
                    awarded=0,
                    cumulative_score=0,
                    correct_flag_count=int(getattr(challenge, "correct_flag_count", 0) or 0),
                    total_flag_count=int(getattr(challenge, "flag_count", 0) or 0),
                    matched_flag_index=None,
                    duplicate=True,
                )
            raise

    def close_challenge(self, unique_code: str) -> bool:
        payload = self._request(
            "POST",
            "/openapi/v1/challenges/close",
            query={"unique_code": unique_code},
        ) or {}
        return bool(payload.get("closed"))
