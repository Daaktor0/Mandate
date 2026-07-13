"""Typed, privacy-minimised company-data provider boundary.

The public interface accepts only a legal name or CIN.  It intentionally cannot
carry user identity, firm, billing, letterhead, or confidential matter data.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal, Protocol, Self

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from mandate_worker.fixtures import AdapterCapability, FixtureCatalog
from mandate_worker.runtime import RuntimeAdapterPlan

CIN_PATTERN: Final = re.compile(r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")
MAX_LEGAL_NAME_LENGTH: Final = 300
MAX_RESULTS: Final = 20
MAX_PROVIDER_CALLS: Final = 2
MAX_RESPONSE_BYTES: Final = 1_048_576
ATTESTR_SEARCH_URL: Final = "https://api.attestr.com/api/v2/public/corpx/business/search"
ATTESTR_MASTER_URL: Final = "https://api.attestr.com/api/v2/public/corpx/business/master"


class CompanyDataOperation(StrEnum):
    SEARCH_BY_NAME = "search_by_name"
    LOOKUP_BY_CIN = "lookup_by_cin"


class CompanyDataRecord(BaseModel):
    """Allowlisted public company fields used during entity resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cin: str = Field(pattern=CIN_PATTERN.pattern)
    legal_name: str = Field(min_length=1, max_length=MAX_LEGAL_NAME_LENGTH)
    former_names: tuple[str, ...] = Field(default=(), max_length=20)
    company_type: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=100)
    active: bool | None = None
    incorporated_date: date | None = None
    listed: bool | None = None
    registered_office_state: str | None = Field(default=None, max_length=100)
    registered_office_summary: str | None = Field(default=None, max_length=500)
    source_record_id: str = Field(min_length=1, max_length=64)

    @field_validator("cin", mode="before")
    @classmethod
    def normalise_cin(cls, value: object) -> str:
        return _normalise_cin(value)

    @field_validator("legal_name", mode="before")
    @classmethod
    def normalise_name(cls, value: object) -> str:
        return _normalise_legal_name(value)

    @field_validator("former_names", mode="before")
    @classmethod
    def normalise_former_names(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            values = (value,)
        elif isinstance(value, list | tuple):
            values = tuple(value)
        else:
            raise ValueError("former_names must be a string or sequence")
        return tuple(_normalise_legal_name(item) for item in values)


class CompanyDataResponse(BaseModel):
    """Bounded result with concise audit and cost-accounting metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: CompanyDataOperation
    public_query: str = Field(min_length=1, max_length=MAX_LEGAL_NAME_LENGTH)
    provider: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_-]+$")
    fixture: bool
    provider_calls: int = Field(ge=0, le=MAX_PROVIDER_CALLS)
    records: tuple[CompanyDataRecord, ...] = Field(max_length=MAX_RESULTS)


class CompanyDataProvider(Protocol):
    """Company master-data capability used by candidate generation."""

    async def search_by_name(self, legal_name: str, *, limit: int = 10) -> CompanyDataResponse:
        """Find company records using a public legal name."""

    async def lookup_by_cin(self, cin: str) -> CompanyDataResponse:
        """Look up one company using an exact CIN."""


class CompanyDataConfigurationError(RuntimeError):
    """Provider selection or credentials are absent or unsafe."""


class CompanyDataProviderError(RuntimeError):
    """Stable provider failure that never includes a raw response or secret."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class CompanyDataTransportError(RuntimeError):
    """Sanitised transport failure."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class CompanyDataHttpResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status_code: int = Field(ge=100, le=599)
    content_type: str | None = Field(default=None, max_length=200)
    body: bytes = Field(max_length=MAX_RESPONSE_BYTES)


class AttestrTransport(Protocol):
    async def post_json(
        self,
        operation: CompanyDataOperation,
        payload: Mapping[str, object],
    ) -> CompanyDataHttpResponse:
        """POST an allowlisted payload to the fixed endpoint for an operation."""


@dataclass(frozen=True, slots=True)
class AttestrHttpTransport:
    """No-proxy, no-redirect transport restricted to Attestr's fixed v2 endpoints."""

    auth_token: str = field(repr=False)
    timeout_seconds: float = 8.0
    max_response_bytes: int = MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if not self.auth_token.strip():
            raise CompanyDataConfigurationError("company_data_credentials_missing")
        if not 0 < self.timeout_seconds <= 15:
            raise CompanyDataConfigurationError("company_data_timeout_invalid")
        if not 1 <= self.max_response_bytes <= MAX_RESPONSE_BYTES:
            raise CompanyDataConfigurationError("company_data_response_cap_invalid")

    async def post_json(
        self,
        operation: CompanyDataOperation,
        payload: Mapping[str, object],
    ) -> CompanyDataHttpResponse:
        endpoints = {
            CompanyDataOperation.SEARCH_BY_NAME: ATTESTR_SEARCH_URL,
            CompanyDataOperation.LOOKUP_BY_CIN: ATTESTR_MASTER_URL,
        }
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Authorization": f"Basic {self.auth_token}",
            "Content-Type": "application/json",
            "User-Agent": "Mandate-CompanyDataProvider/1.0",
        }
        timeout = httpx.Timeout(self.timeout_seconds)
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                trust_env=False,
                timeout=timeout,
            ) as client:
                async with client.stream(
                    "POST",
                    endpoints[operation],
                    headers=headers,
                    json=dict(payload),
                ) as response:
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        body.extend(chunk)
                        if len(body) > self.max_response_bytes:
                            raise CompanyDataTransportError(
                                "company_data_response_too_large", retryable=False
                            )
                    return CompanyDataHttpResponse(
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type"),
                        body=bytes(body),
                    )
        except CompanyDataTransportError:
            raise
        except httpx.TransportError as error:
            raise CompanyDataTransportError(
                "company_data_transport_failed", retryable=True
            ) from error


class _FixtureAddress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    state: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=500)


class _FixtureCompanyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    cin: str = Field(pattern=CIN_PATTERN.pattern)
    legal_name: str = Field(alias="legalName", min_length=1, max_length=MAX_LEGAL_NAME_LENGTH)
    former_names: tuple[str, ...] = Field(default=(), alias="formerNames", max_length=20)
    company_type: str | None = Field(default=None, alias="companyType", max_length=100)
    status: str | None = Field(default=None, max_length=100)
    active: bool | None = None
    incorporated_date: date | None = Field(default=None, alias="incorporatedDate")
    listed: bool | None = None
    registered_office: _FixtureAddress | None = Field(default=None, alias="registeredOffice")


class _FixtureNameSearch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    legal_name: str = Field(alias="legalName", min_length=1, max_length=MAX_LEGAL_NAME_LENGTH)
    cins: tuple[str, ...] = Field(min_length=1, max_length=MAX_RESULTS)


class _CompanyDataFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    fixture_version: Literal[1] = Field(alias="fixtureVersion")
    notice: Literal["Synthetic fixture; not an MCA or legal-database result."]
    records: tuple[_FixtureCompanyRecord, ...] = Field(min_length=1, max_length=100)
    name_searches: tuple[_FixtureNameSearch, ...] = Field(alias="nameSearches", min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        record_cins = [record.cin for record in self.records]
        if len(record_cins) != len(set(record_cins)):
            raise ValueError("fixture company CINs must be unique")
        search_names = [_normalise_lookup_key(item.legal_name) for item in self.name_searches]
        if len(search_names) != len(set(search_names)):
            raise ValueError("fixture company searches must be unique")
        unknown = {
            cin for item in self.name_searches for cin in item.cins if cin not in record_cins
        }
        if unknown:
            raise ValueError("fixture company search references an unknown CIN")
        return self


@dataclass(frozen=True, slots=True)
class FixtureCompanyDataProvider:
    """Deterministic, zero-spend company-data implementation for DEMO_MODE."""

    records_by_cin: Mapping[str, CompanyDataRecord]
    cins_by_name: Mapping[str, tuple[str, ...]]

    @classmethod
    def from_catalog(cls, catalog: FixtureCatalog) -> FixtureCompanyDataProvider:
        try:
            fixture = _CompanyDataFixture.model_validate(
                catalog.payload(AdapterCapability.COMPANY_DATA)
            )
            records = {
                item.cin: CompanyDataRecord(
                    cin=item.cin,
                    legal_name=item.legal_name,
                    former_names=item.former_names,
                    company_type=item.company_type,
                    status=item.status,
                    active=item.active,
                    incorporated_date=item.incorporated_date,
                    listed=item.listed,
                    registered_office_state=(
                        item.registered_office.state if item.registered_office else None
                    ),
                    registered_office_summary=(
                        item.registered_office.summary if item.registered_office else None
                    ),
                    source_record_id=item.cin,
                )
                for item in fixture.records
            }
            searches = {
                _normalise_lookup_key(item.legal_name): item.cins for item in fixture.name_searches
            }
        except (KeyError, ValidationError, ValueError) as error:
            raise CompanyDataConfigurationError("company_data_fixture_invalid") from error
        return cls(
            records_by_cin=MappingProxyType(records),
            cins_by_name=MappingProxyType(searches),
        )

    async def search_by_name(self, legal_name: str, *, limit: int = 10) -> CompanyDataResponse:
        query = _normalise_legal_name(legal_name)
        checked_limit = _validate_limit(limit)
        cins = self.cins_by_name.get(_normalise_lookup_key(query), ())[:checked_limit]
        return CompanyDataResponse(
            operation=CompanyDataOperation.SEARCH_BY_NAME,
            public_query=query,
            provider="fixture",
            fixture=True,
            provider_calls=0,
            records=tuple(self.records_by_cin[cin] for cin in cins),
        )

    async def lookup_by_cin(self, cin: str) -> CompanyDataResponse:
        query = _normalise_cin(cin)
        record = self.records_by_cin.get(query)
        return CompanyDataResponse(
            operation=CompanyDataOperation.LOOKUP_BY_CIN,
            public_query=query,
            provider="fixture",
            fixture=True,
            provider_calls=0,
            records=(record,) if record is not None else (),
        )


class _AttestrAddress(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    type: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    full_address: str | None = Field(default=None, alias="fullAddress", max_length=2000)
    active: bool | None = None


class _AttestrSearchRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    index_id: str = Field(alias="indexId", min_length=1, max_length=64)
    business_name: str = Field(alias="businessName", min_length=1, max_length=MAX_LEGAL_NAME_LENGTH)
    type: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=100)
    active: bool | None = None
    incorporated_date: str | None = Field(default=None, alias="incorporatedDate", max_length=20)
    addresses: tuple[_AttestrAddress, ...] = Field(default=(), max_length=100)


class _AttestrMasterRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    valid: bool
    reg: str | None = Field(default=None, max_length=64)
    business_name: str | None = Field(
        default=None, alias="businessName", max_length=MAX_LEGAL_NAME_LENGTH
    )
    type: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=100)
    active: bool | None = None
    incorporated_date: str | None = Field(default=None, alias="incorporatedDate", max_length=20)
    listed: bool | None = None
    previous_name: str | None = Field(
        default=None, alias="previousName", max_length=MAX_LEGAL_NAME_LENGTH
    )
    addresses: tuple[_AttestrAddress, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def valid_record_has_identity(self) -> Self:
        if self.valid and (self.reg is None or self.business_name is None):
            raise ValueError("valid company response is missing identity fields")
        return self


Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class AttestrCompanyDataProvider:
    """Attestr v2 adapter with bounded calls and allowlisted response fields."""

    transport: AttestrTransport
    max_provider_calls: int = MAX_PROVIDER_CALLS
    retry_delay_seconds: float = 0.25
    sleeper: Sleep = field(default=asyncio.sleep, repr=False)

    def __post_init__(self) -> None:
        if not 1 <= self.max_provider_calls <= MAX_PROVIDER_CALLS:
            raise CompanyDataConfigurationError("company_data_call_cap_invalid")
        if not 0 <= self.retry_delay_seconds <= 2:
            raise CompanyDataConfigurationError("company_data_retry_delay_invalid")

    async def search_by_name(self, legal_name: str, *, limit: int = 10) -> CompanyDataResponse:
        query = _normalise_legal_name(legal_name)
        checked_limit = _validate_limit(limit)
        payload: Mapping[str, object] = MappingProxyType(
            {
                "businessName": {"matchCriteria": "EQUALS", "matchValue": query},
                "skip": 0,
                "limit": checked_limit,
                "sort": "score",
                "sortOrder": -1,
            }
        )
        response, calls = await self._request(CompanyDataOperation.SEARCH_BY_NAME, payload)
        records = self._parse_search(response.body, limit=checked_limit)
        return CompanyDataResponse(
            operation=CompanyDataOperation.SEARCH_BY_NAME,
            public_query=query,
            provider="attestr",
            fixture=False,
            provider_calls=calls,
            records=records,
        )

    async def lookup_by_cin(self, cin: str) -> CompanyDataResponse:
        query = _normalise_cin(cin)
        payload: Mapping[str, object] = MappingProxyType(
            {"reg": query, "charges": False, "efilings": False}
        )
        response, calls = await self._request(CompanyDataOperation.LOOKUP_BY_CIN, payload)
        record = self._parse_master(response.body, expected_cin=query)
        return CompanyDataResponse(
            operation=CompanyDataOperation.LOOKUP_BY_CIN,
            public_query=query,
            provider="attestr",
            fixture=False,
            provider_calls=calls,
            records=(record,) if record is not None else (),
        )

    async def _request(
        self,
        operation: CompanyDataOperation,
        payload: Mapping[str, object],
    ) -> tuple[CompanyDataHttpResponse, int]:
        last_error: CompanyDataProviderError | None = None
        for call_number in range(1, self.max_provider_calls + 1):
            provider_error: CompanyDataProviderError | None
            try:
                response = await self.transport.post_json(operation, payload)
            except CompanyDataTransportError as error:
                provider_error = CompanyDataProviderError(error.code, retryable=error.retryable)
            else:
                provider_error = _classify_http_failure(response)
                if provider_error is None:
                    return response, call_number

            assert provider_error is not None
            last_error = provider_error
            if not provider_error.retryable or call_number == self.max_provider_calls:
                raise provider_error from None
            await self.sleeper(self.retry_delay_seconds * call_number)

        if last_error is None:  # pragma: no cover - range is non-empty by construction
            raise CompanyDataProviderError("company_data_unavailable", retryable=True)
        raise last_error

    @staticmethod
    def _parse_search(body: bytes, *, limit: int) -> tuple[CompanyDataRecord, ...]:
        try:
            payload = json.loads(body)
            if not isinstance(payload, list):
                raise ValueError("company search response must be a list")
            raw_records = tuple(
                _AttestrSearchRecord.model_validate(item) for item in payload[:limit]
            )
            return tuple(_search_record_to_company(item) for item in raw_records)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError):
            raise CompanyDataProviderError(
                "company_data_response_invalid", retryable=False
            ) from None

    @staticmethod
    def _parse_master(body: bytes, *, expected_cin: str) -> CompanyDataRecord | None:
        try:
            payload = json.loads(body)
            raw = _AttestrMasterRecord.model_validate(payload)
            if not raw.valid:
                return None
            if raw.reg != expected_cin:
                raise ValueError("company response registration identifier mismatch")
            return _master_record_to_company(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError):
            raise CompanyDataProviderError(
                "company_data_response_invalid", retryable=False
            ) from None


def build_company_data_provider(
    plan: RuntimeAdapterPlan,
    environ: Mapping[str, str] | None = None,
    *,
    attestr_transport: AttestrTransport | None = None,
) -> CompanyDataProvider:
    """Build the selected provider without a credential-driven fallback."""

    binding = plan.bindings[AdapterCapability.COMPANY_DATA]
    if binding == "fixture":
        if not plan.demo_mode or plan.catalog is None:
            raise CompanyDataConfigurationError("company_data_fixture_requires_demo_mode")
        return FixtureCompanyDataProvider.from_catalog(plan.catalog)
    if binding == "attestr":
        environment = os.environ if environ is None else environ
        token = environment.get("ATTESTR_AUTH_TOKEN", "").strip()
        if attestr_transport is None:
            if not token:
                raise CompanyDataConfigurationError("company_data_credentials_missing")
            attestr_transport = AttestrHttpTransport(token)
        return AttestrCompanyDataProvider(attestr_transport)
    if binding == "unconfigured":
        raise CompanyDataConfigurationError("company_data_provider_unconfigured")
    raise CompanyDataConfigurationError("company_data_provider_not_allowlisted")


def _normalise_legal_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("legal name must be a string")
    name = " ".join(value.split())
    if not name or len(name) > MAX_LEGAL_NAME_LENGTH:
        raise ValueError("legal name is empty or exceeds the provider limit")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ValueError("legal name contains control characters")
    return name


def _normalise_lookup_key(value: str) -> str:
    return _normalise_legal_name(value).casefold()


def _normalise_cin(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("CIN must be a string")
    cin = value.strip().upper()
    if CIN_PATTERN.fullmatch(cin) is None:
        raise ValueError("CIN is invalid")
    return cin


def _validate_limit(limit: int) -> int:
    if isinstance(limit, bool) or not 1 <= limit <= MAX_RESULTS:
        raise ValueError(f"company-data result limit must be between 1 and {MAX_RESULTS}")
    return limit


def _classify_http_failure(response: CompanyDataHttpResponse) -> CompanyDataProviderError | None:
    if response.status_code == 200:
        media_type = (response.content_type or "").partition(";")[0].strip().lower()
        if media_type != "application/json":
            return CompanyDataProviderError("company_data_response_invalid", retryable=False)
        return None
    if response.status_code == 400:
        return CompanyDataProviderError("company_data_invalid_request", retryable=False)
    if response.status_code in {401, 403}:
        return CompanyDataProviderError("company_data_unauthorized", retryable=False)
    if response.status_code == 429:
        return CompanyDataProviderError("company_data_rate_limited", retryable=True)
    if 500 <= response.status_code <= 599:
        return CompanyDataProviderError("company_data_unavailable", retryable=True)
    return CompanyDataProviderError("company_data_http_error", retryable=False)


def _registered_office(
    addresses: tuple[_AttestrAddress, ...],
) -> tuple[str | None, str | None]:
    registered = [
        address
        for address in addresses
        if address.type is not None and "registered" in address.type.casefold()
    ]
    selected = next((address for address in registered if address.active is True), None)
    if selected is None and registered:
        selected = registered[0]
    if selected is None:
        return None, None
    summary = selected.full_address[:500] if selected.full_address else None
    return selected.state, summary


def _parse_attestr_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%d-%m-%Y").date()
    except ValueError as error:
        raise ValueError("provider date is invalid") from error


def _search_record_to_company(raw: _AttestrSearchRecord) -> CompanyDataRecord:
    state, summary = _registered_office(raw.addresses)
    return CompanyDataRecord(
        cin=raw.index_id,
        legal_name=raw.business_name,
        company_type=raw.type,
        status=raw.status,
        active=raw.active,
        incorporated_date=_parse_attestr_date(raw.incorporated_date),
        registered_office_state=state,
        registered_office_summary=summary,
        source_record_id=raw.index_id,
    )


def _master_record_to_company(raw: _AttestrMasterRecord) -> CompanyDataRecord:
    if raw.reg is None or raw.business_name is None:
        raise ValueError("valid company response is missing identity fields")
    state, summary = _registered_office(raw.addresses)
    former_names = (raw.previous_name,) if raw.previous_name else ()
    return CompanyDataRecord(
        cin=raw.reg,
        legal_name=raw.business_name,
        former_names=former_names,
        company_type=raw.type,
        status=raw.status,
        active=raw.active,
        incorporated_date=_parse_attestr_date(raw.incorporated_date),
        listed=raw.listed,
        registered_office_state=state,
        registered_office_summary=summary,
        source_record_id=raw.reg,
    )
