"""Member bulk-import ETL pipeline (ROADMAP.md Phase 15c).

Extract  -> one pandas DataFrame, whatever the source format (.xlsx / .csv / .json)
Transform -> canonical headers, coerced types, vectorised validation, within-file
             dedup, CSV/Excel formula-injection neutralisation
Load      -> done by PlatformAdminTenantService.bulk_import_members (idempotent
             update_or_create by email, chunked, one transaction per chunk)

Pure functions only -- no ORM, no request/response objects, no Django imports at
module load. pandas / openpyxl are imported lazily inside the functions that need
them (same "only pay for it when it's actually used" pattern as boto3/openai
elsewhere in this codebase).
"""
import io
import json
import re

from apps.common.enums import Language, OrgRoleLevel
from apps.common.exceptions import ValidationError

SUPPORTED_EXTENSIONS = (".xlsx", ".csv", ".json")

# Hard cap -- an ops member list is dozens to low-hundreds of rows; anything
# larger is almost certainly a wrong file, and we don't want to hold a huge
# frame + N transactions open. Chunking (in the service) keeps each transaction
# small; this bounds the whole job.
MAX_ROWS = 5000

# The report's `row` is 1-based and counts the header as row 1 -- i.e. it matches
# what the operator sees in Excel / a spreadsheet view. For JSON input there's no
# header row, so `row` 2 == the first array element (documented in api-spec §22).
_ROW_OFFSET = 2

# Every messy real-world header variant -> one canonical snake_case name.
_HEADER_ALIASES = {
    "name": "name",
    "full name": "name",
    "member name": "name",
    "email": "email",
    "e-mail": "email",
    "email address": "email",
    "mail": "email",
    "role": "role_level",
    "role level": "role_level",
    "rolelevel": "role_level",
    "role_level": "role_level",
    "role label": "role_label",
    "role_label": "role_label",
    "designation": "role_label",
    "title": "role_label",
    "phone": "phone",
    "mobile": "phone",
    "phone number": "phone",
    "can broadcast": "can_broadcast",
    "can_broadcast": "can_broadcast",
    "broadcast": "can_broadcast",
    "language": "preferred_lang",
    "preferred language": "preferred_lang",
    "preferred_lang": "preferred_lang",
    "lang": "preferred_lang",
}

_REQUIRED_COLUMNS = ("name", "email", "role_level")
_OPTIONAL_COLUMNS = ("role_label", "phone", "can_broadcast", "preferred_lang")

_BOOL_TRUE = {"true", "yes", "y", "1", "t"}
_BOOL_FALSE = {"false", "no", "n", "0", "f", ""}

# A cell starting with one of these can execute as a formula if the data is ever
# re-exported and reopened in a spreadsheet -- neutralise on ingest by prefixing
# a single quote (Excel's own "treat as text" marker). Defence in depth: this
# project has no re-export feature today.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_VALID_ROLES = set(OrgRoleLevel.values)
_VALID_LANGS = set(Language.values)


def _neutralise_formula(value: str) -> str:
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


# ---------------------------------------------------------------- Extract

def extract(file_bytes: bytes, filename: str):
    """(raw upload bytes, original filename) -> a pandas DataFrame of strings.

    Raises ValidationError(code="INVALID_FILE") for an unreadable / unsupported
    file. All cells come back as stripped strings with NaN -> "" so the Transform
    stage never has to think about dtypes or nulls.
    """
    import pandas as pd

    ext = _extension(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '{ext}'. Use .xlsx, .csv, or .json.",
            code="INVALID_FILE",
        )

    try:
        if ext == ".xlsx":
            # sheet_name=0 -> first sheet only; dtype=str -> no "1" -> 1.0 coercion.
            df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl", sheet_name=0, dtype=str)
        elif ext == ".csv":
            df = _read_csv_any_encoding(pd, file_bytes)
        else:
            df = _read_json(pd, file_bytes)
    except ValidationError:
        raise
    except Exception as exc:  # pandas/openpyxl/json parse failures
        raise ValidationError(f"Could not parse the file: {exc}", code="INVALID_FILE") from exc

    df = df.dropna(axis=0, how="all")  # drop fully-blank rows (trailing Excel rows)
    df = df.fillna("")
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()
    return df


def _extension(filename: str) -> str:
    name = (filename or "").lower()
    dot = name.rfind(".")
    return name[dot:] if dot != -1 else ""


def _read_csv_any_encoding(pd, file_bytes: bytes):
    # utf-8-sig transparently eats a UTF-8 BOM (the #1 "why is my first header
    # mangled" bug from Excel-exported CSVs). Fall back to latin-1, which can
    # decode any byte sequence, rather than 500 on a stray non-UTF-8 byte.
    try:
        return pd.read_csv(io.BytesIO(file_bytes), dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(io.BytesIO(file_bytes), dtype=str, encoding="latin-1")


def _read_json(pd, file_bytes: bytes):
    payload = json.loads(file_bytes.decode("utf-8-sig"))
    if isinstance(payload, dict):
        # accept {"members": [...]} / {"rows": [...]} / {"data": [...]}
        for key in ("members", "rows", "data", "records"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise ValidationError(
            "JSON must be an array of objects, or an object with a 'members' array.",
            code="INVALID_FILE",
        )
    return pd.DataFrame(payload, dtype=str)


# ---------------------------------------------------------------- Transform

def transform(df):
    """DataFrame -> (valid_records, errors).

    valid_records: list of dicts ready for the Load step, each carrying a private
                   "_row" key (the source row number, for error reporting on a
                   Load-time conflict).
    errors:        list of {"row", "field", "reason"} -- one per rejected row.

    Raises ValidationError(code="INVALID_FILE") only for whole-file problems
    (missing a required column, empty file, over the row cap) -- a single bad
    row is an entry in `errors`, never a raised exception.
    """
    import pandas as pd

    df = _normalise_headers(df)

    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValidationError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Expected headers map to: {', '.join(_REQUIRED_COLUMNS + _OPTIONAL_COLUMNS)}.",
            code="INVALID_FILE",
        )
    for col in _OPTIONAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    if len(df) == 0:
        raise ValidationError("The file has no data rows.", code="INVALID_FILE")
    if len(df) > MAX_ROWS:
        raise ValidationError(
            f"Too many rows ({len(df)}); the limit is {MAX_ROWS} per import.",
            code="INVALID_FILE",
        )

    # --- clean / coerce (all vectorised) ---
    df["email"] = df["email"].str.strip().str.lower()
    df["role_level"] = df["role_level"].str.strip().str.upper()
    df["name"] = df["name"].map(_neutralise_formula)
    df["role_label"] = df["role_label"].map(_neutralise_formula).replace("", None)
    df["phone"] = df["phone"].map(_neutralise_formula).replace("", None)
    df["preferred_lang"] = (
        df["preferred_lang"].str.strip().str.upper().where(lambda s: s.isin(_VALID_LANGS), "EN")
    )
    df["can_broadcast"] = _coerce_bool(df["can_broadcast"])

    # --- vectorised validation ---
    df["_email_ok"] = df["email"].str.match(_EMAIL_RE, na=False)
    df["_role_ok"] = df["role_level"].isin(_VALID_ROLES)
    df["_name_ok"] = df["name"].str.strip().str.len() > 0
    # last occurrence wins; earlier duplicates of the same email are "skipped"
    df["_dup"] = df["email"].duplicated(keep="last") & df["_email_ok"]

    df = df.reset_index(drop=True)
    valid_records, errors = [], []
    for idx, row in df.iterrows():
        row_no = int(idx) + _ROW_OFFSET
        if not row["_name_ok"]:
            errors.append({"row": row_no, "field": "name", "reason": "name is required"})
            continue
        if not row["_email_ok"]:
            errors.append({"row": row_no, "field": "email", "reason": "not a valid email address"})
            continue
        if not row["_role_ok"]:
            errors.append({
                "row": row_no, "field": "roleLevel",
                "reason": f"must be one of {', '.join(sorted(_VALID_ROLES))}",
            })
            continue
        if row["_dup"]:
            errors.append({
                "row": row_no, "field": "email",
                "reason": "duplicate email within the file (a later row was used instead)",
            })
            continue
        valid_records.append({
            "_row": row_no,
            "name": row["name"].strip(),
            "email": row["email"],
            "role_level": row["role_level"],
            "role_label": _none_if_nan(pd, row["role_label"]),
            "phone": _none_if_nan(pd, row["phone"]),
            "can_broadcast": bool(row["can_broadcast"]),
            "preferred_lang": row["preferred_lang"],
        })
    return valid_records, errors


def _normalise_headers(df):
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df.rename(columns=_HEADER_ALIASES)
    # collapse any accidental duplicate canonical columns (keep the first)
    df = df.loc[:, ~df.columns.duplicated()]
    return df


def _coerce_bool(series):
    lowered = series.astype(str).str.strip().str.lower()
    return lowered.map(lambda v: True if v in _BOOL_TRUE else False)


def _none_if_nan(pd, value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value or None
