import io
import os
import tempfile
import zipfile
from datetime import date

from app.services.sec_13f import _normalize_name, _num, _parse_sec_date, parse_holdings


def test_parse_sec_date():
    assert _parse_sec_date("31-MAR-2026") == date(2026, 3, 31)
    assert _parse_sec_date("01-JAN-2025") == date(2025, 1, 1)
    assert _parse_sec_date("") is None
    assert _parse_sec_date("garbage") is None
    assert _parse_sec_date(None) is None


def test_num():
    assert _num("403780") == 403780.0
    assert _num("") is None
    assert _num(None) is None
    assert _num("x") is None


def test_normalize_name_strips_suffixes():
    # 公司后缀/标点去除后应能匹配
    assert _normalize_name("Apple Inc.") == _normalize_name("APPLE INC")
    assert _normalize_name("IREN Limited") == "IREN"
    assert _normalize_name("Costar Group, Inc.") == "COSTAR"


def _make_zip(tmpdir, submission, coverpage, infotable):
    path = os.path.join(tmpdir, "t.zip")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("SUBMISSION.tsv", submission)
        zf.writestr("COVERPAGE.tsv", coverpage)
        zf.writestr("INFOTABLE.tsv", infotable)
    return path


def test_parse_holdings_exact_cusip_hit():
    submission = (
        "ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT\n"
        "acc-1\t15-MAY-2026\t13F-HR\t0001\t31-MAR-2026\n"
        "acc-2\t15-MAY-2026\t13F-NT\t0002\t31-MAR-2026\n"
    )
    coverpage = (
        "ACCESSION_NUMBER\tREPORTCALENDARORQUARTER\tISAMENDMENT\tAMENDMENTNO\tAMENDMENTTYPE\tCONFDENIEDEXPIRED\tDATEDENIEDEXPIRED\tDATEREPORTED\tREASONFORNONCONFIDENTIALITY\tFILINGMANAGER_NAME\n"
        "acc-1\t31-MAR-2026\tN\t\t\t\t\t\t\tBig Hedge Fund LP\n"
    )
    infotable = (
        "ACCESSION_NUMBER\tINFOTABLE_SK\tNAMEOFISSUER\tTITLEOFCLASS\tCUSIP\tFIGI\tVALUE\tSSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL\tINVESTMENTDISCRETION\tOTHERMANAGER\tVOTING_AUTH_SOLE\tVOTING_AUTH_SHARED\tVOTING_AUTH_NONE\n"
        "acc-1\t1\tAPPLE INC\tCOM\t037833100\t\t403780\t1591\tSH\t\tSOLE\t\t1591\t0\t0\n"
        "acc-1\t2\tSOME OTHER CO\tCOM\t999999999\t\t100\t5\tSH\t\tSOLE\t\t5\t0\t0\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = _make_zip(tmp, submission, coverpage, infotable)
        holdings, discovered = parse_holdings(path, {"037833100": "AAPL"}, {})
    assert len(holdings) == 1
    h = holdings[0]
    assert h.ticker == "AAPL"
    assert h.manager_name == "Big Hedge Fund LP"
    assert h.report_period == date(2026, 3, 31)
    assert h.value_usd == 403780.0
    assert h.shares == 1591.0
    assert discovered == {}


def test_parse_holdings_issuer_name_match_and_discover():
    submission = (
        "ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT\n"
        "acc-1\t15-MAY-2026\t13F-HR\t0001\t31-MAR-2026\n"
    )
    coverpage = (
        "ACCESSION_NUMBER\tREPORTCALENDARORQUARTER\tISAMENDMENT\tAMENDMENTNO\tAMENDMENTTYPE\tCONFDENIEDEXPIRED\tDATEDENIEDEXPIRED\tDATEREPORTED\tREASONFORNONCONFIDENTIALITY\tFILINGMANAGER_NAME\n"
        "acc-1\t31-MAR-2026\tN\t\t\t\t\t\t\tQuant Capital\n"
    )
    infotable = (
        "ACCESSION_NUMBER\tINFOTABLE_SK\tNAMEOFISSUER\tTITLEOFCLASS\tCUSIP\tFIGI\tVALUE\tSSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL\tINVESTMENTDISCRETION\tOTHERMANAGER\tVOTING_AUTH_SOLE\tVOTING_AUTH_SHARED\tVOTING_AUTH_NONE\n"
        "acc-1\t1\tIREN LTD\tCOM\t45840M108\t\t500000\t20000\tSH\t\tSOLE\t\t20000\t0\t0\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = _make_zip(tmp, submission, coverpage, infotable)
        # 无已知 CUSIP，靠归一化公司名 "IREN" 命中
        holdings, discovered = parse_holdings(path, {}, {"IREN": "IREN"})
    assert len(holdings) == 1
    assert holdings[0].ticker == "IREN"
    assert holdings[0].cusip == "45840M108"
    assert discovered == {"45840M108": ("IREN", "IREN LTD")}
