from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any


@dataclass(frozen=True)
class EnterpriseTopic:
    slug: str
    name: str
    keywords: tuple[str, ...]


ENTERPRISE_TOPICS: tuple[EnterpriseTopic, ...] = (
    EnterpriseTopic(
        slug="doanh_nghiep",
        name="Doanh nghiệp",
        keywords=(
            "doanh nghiệp",
            "doanh nghiep",
            "đăng ký doanh nghiệp",
            "dang ky doanh nghiep",
            "đăng ký kinh doanh",
            "dang ky kinh doanh",
            "hộ kinh doanh",
            "ho kinh doanh",
            "công ty",
            "cong ty",
            "hợp tác xã",
            "hop tac xa",
            "chi nhánh",
            "chi nhanh",
            "văn phòng đại diện",
            "van phong dai dien",
            "thành lập doanh nghiệp",
            "thanh lap doanh nghiep",
            "giải thể doanh nghiệp",
            "giai the doanh nghiep",
        ),
    ),
    EnterpriseTopic(
        slug="dau_tu",
        name="Đầu tư",
        keywords=(
            "đầu tư",
            "dau tu",
            "nhà đầu tư",
            "nha dau tu",
            "vốn đầu tư",
            "von dau tu",
            "dự án đầu tư",
            "du an dau tu",
            "giấy chứng nhận đăng ký đầu tư",
            "khu công nghiệp",
            "khu kinh tế",
        ),
    ),
    EnterpriseTopic(
        slug="thuong_mai",
        name="Kinh doanh - Thương mại",
        keywords=(
            "kinh doanh",
            "thương mại",
            "thuong mai",
            "mua bán hàng hóa",
            "cung ứng dịch vụ",
            "hoạt động thương mại",
            "xúc tiến thương mại",
            "đại lý thương mại",
            "nhượng quyền thương mại",
            "franchise",
        ),
    ),
    EnterpriseTopic(
        slug="hop_dong",
        name="Hợp đồng",
        keywords=(
            "hợp đồng",
            "hop dong",
            "hợp đồng thương mại",
            "hợp đồng kinh tế",
            "hợp đồng mua bán",
            "hợp đồng dịch vụ",
            "giao kết hợp đồng",
            "thực hiện hợp đồng",
            "vi phạm hợp đồng",
        ),
    ),
    EnterpriseTopic(
        slug="lao_dong",
        name="Lao động",
        keywords=(
            "lao động",
            "lao dong",
            "người lao động",
            "nguoi lao dong",
            "người sử dụng lao động",
            "hợp đồng lao động",
            "tiền lương",
            "tien luong",
            "bảo hiểm xã hội",
            "bao hiem xa hoi",
            "bảo hiểm thất nghiệp",
            "bao hiem that nghiep",
            "bảo hiểm y tế",
            "bao hiem y te",
            "an toàn lao động",
            "vệ sinh lao động",
        ),
    ),
    EnterpriseTopic(
        slug="thue",
        name="Thuế",
        keywords=(
            "thuế",
            "thue",
            "quản lý thuế",
            "quan ly thue",
            "thuế giá trị gia tăng",
            "thuế gtgt",
            "vat",
            "thuế thu nhập doanh nghiệp",
            "tndn",
            "thuế thu nhập cá nhân",
            "tncn",
            "thuế tiêu thụ đặc biệt",
            "thuế xuất khẩu",
            "thuế nhập khẩu",
        ),
    ),
    EnterpriseTopic(
        slug="hoa_don",
        name="Hóa đơn",
        keywords=(
            "hóa đơn",
            "hoa don",
            "hóa đơn điện tử",
            "hoa don dien tu",
            "chứng từ",
            "chung tu",
        ),
    ),
    EnterpriseTopic(
        slug="ke_toan_kiem_toan",
        name="Kế toán - Kiểm toán",
        keywords=(
            "kế toán",
            "ke toan",
            "kiểm toán",
            "kiem toan",
            "kiểm toán độc lập",
            "báo cáo tài chính",
            "bao cao tai chinh",
            "sổ kế toán",
            "chuẩn mực kế toán",
        ),
    ),
    EnterpriseTopic(
        slug="chung_khoan",
        name="Chứng khoán",
        keywords=(
            "chứng khoán",
            "chung khoan",
            "cổ phiếu",
            "co phieu",
            "trái phiếu",
            "trai phieu",
            "niêm yết",
            "niem yet",
            "công ty đại chúng",
            "thị trường chứng khoán",
        ),
    ),
    EnterpriseTopic(
        slug="ngan_hang_tai_chinh",
        name="Ngân hàng - Tài chính",
        keywords=(
            "ngân hàng",
            "ngan hang",
            "tổ chức tín dụng",
            "to chuc tin dung",
            "vay vốn",
            "tín dụng",
            "bao lãnh ngân hàng",
            "thanh toán",
            "thanh toán không dùng tiền mặt",
        ),
    ),
    EnterpriseTopic(
        slug="canh_tranh",
        name="Cạnh tranh",
        keywords=(
            "cạnh tranh",
            "canh tranh",
            "cạnh tranh không lành mạnh",
            "thỏa thuận hạn chế cạnh tranh",
            "tập trung kinh tế",
        ),
    ),
    EnterpriseTopic(
        slug="pha_san",
        name="Phá sản",
        keywords=(
            "phá sản",
            "pha san",
            "mất khả năng thanh toán",
        ),
    ),
    EnterpriseTopic(
        slug="so_huu_tri_tue",
        name="Sở hữu trí tuệ",
        keywords=(
            "sở hữu trí tuệ",
            "so huu tri tue",
            "nhãn hiệu",
            "nhan hieu",
            "sáng chế",
            "sang che",
            "kiểu dáng công nghiệp",
            "bản quyền",
            "ban quyen",
            "quyền tác giả",
            "chỉ dẫn địa lý",
            "chi dẫn địa lý",
            "bí mật kinh doanh",
        ),
    ),
    EnterpriseTopic(
        slug="thuong_mai_dien_tu",
        name="Thương mại điện tử",
        keywords=(
            "thương mại điện tử",
            "thuong mai dien tu",
            "sàn giao dịch thương mại điện tử",
            "website thương mại điện tử",
            "kinh doanh trực tuyến",
        ),
    ),
    EnterpriseTopic(
        slug="xuat_nhap_khau",
        name="Xuất nhập khẩu",
        keywords=(
            "xuất khẩu",
            "xuat khau",
            "nhập khẩu",
            "nhap khau",
            "hải quan",
            "hai quan",
            "xuất xứ hàng hóa",
            "xnk",
        ),
    ),
    EnterpriseTopic(
        slug="logistics",
        name="Logistics",
        keywords=(
            "logistics",
            "vận tải",
            "van tai",
            "giao nhận hàng hóa",
        ),
    ),
    EnterpriseTopic(
        slug="bao_hiem",
        name="Bảo hiểm",
        keywords=(
            "bảo hiểm",
            "bao hiem",
        ),
    ),
    EnterpriseTopic(
        slug="mua_ban_sap_nhap",
        name="Mua bán - Sáp nhập",
        keywords=(
            "mua bán doanh nghiệp",
            "sáp nhập",
            "sap nhap",
            "hợp nhất doanh nghiệp",
            "mua lại doanh nghiệp",
            "m&a",
        ),
    ),
    EnterpriseTopic(
        slug="chuyen_doi_so",
        name="Chuyển đổi số",
        keywords=(
            "chữ ký số",
            "chu ky so",
            "giao dịch điện tử",
            "giao dich dien tu",
        ),
    ),
    EnterpriseTopic(
        slug="dau_thau",
        name="Đấu thầu",
        keywords=(
            "đấu thầu",
            "dau thau",
            "lựa chọn nhà thầu",
        ),
    ),
)

DEFAULT_ENTERPRISE_KEYWORDS = tuple(
    keyword for topic in ENTERPRISE_TOPICS for keyword in topic.keywords
)


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", str(text or ""))
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return stripped.replace("Đ", "D").replace("đ", "d")


def normalize_text_for_match(text: str) -> str:
    text = strip_accents(str(text or "")).lower()
    text = re.sub(r"[\u00a0\t\r\n]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        key = normalize_text_for_match(raw)
        if key in seen:
            continue
        seen.add(key)
        result.append(raw)
    return result


def _flatten_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(_flatten_value(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_value(v) for v in value)
    return str(value)


def _keyword_in_text(normalized_text: str, normalized_keyword: str) -> bool:
    if not normalized_text or not normalized_keyword:
        return False
    compact = re.sub(r"\s+", "", normalized_keyword)
    is_short_code = len(compact) <= 4 and " " not in normalized_keyword
    if is_short_code:
        return re.search(rf"(?<![\w]){re.escape(normalized_keyword)}(?![\w])", normalized_text) is not None
    return normalized_keyword in normalized_text


def match_keywords(fields: dict[str, Any], keywords: list[str] | tuple[str, ...]) -> dict[str, Any]:
    keyword_list = _dedupe(keywords)
    normalized_keywords = [(keyword, normalize_text_for_match(keyword)) for keyword in keyword_list]
    matched_keywords: list[str] = []
    matched_fields: dict[str, list[str]] = {}
    seen_keywords: set[str] = set()

    for field_name, value in fields.items():
        normalized_text = normalize_text_for_match(_flatten_value(value))
        if not normalized_text:
            continue
        for keyword, normalized_keyword in normalized_keywords:
            if not _keyword_in_text(normalized_text, normalized_keyword):
                continue
            if keyword not in seen_keywords:
                seen_keywords.add(keyword)
                matched_keywords.append(keyword)
            matched_fields.setdefault(field_name, []).append(keyword)

    return {
        "is_match": bool(matched_keywords),
        "matched_keywords": matched_keywords,
        "matched_fields": matched_fields,
    }


def topic_choices_text() -> str:
    return ", ".join(topic.slug for topic in ENTERPRISE_TOPICS)


def resolve_topic_slugs(topic_values: list[str] | tuple[str, ...]) -> list[str]:
    if not topic_values:
        return []
    by_slug = {topic.slug: topic.slug for topic in ENTERPRISE_TOPICS}
    by_normalized_name = {normalize_text_for_match(topic.name): topic.slug for topic in ENTERPRISE_TOPICS}
    resolved: list[str] = []
    unknown: list[str] = []
    for value in topic_values:
        raw = str(value or "").strip()
        if not raw:
            continue
        normalized = normalize_text_for_match(raw)
        slug = by_slug.get(raw) or by_normalized_name.get(normalized)
        if not slug:
            unknown.append(raw)
            continue
        if slug not in resolved:
            resolved.append(slug)
    if unknown:
        raise ValueError(f"Unknown enterprise topic(s): {', '.join(unknown)}. Choices: {topic_choices_text()}")
    return resolved


def selected_topics(topic_slugs: list[str] | tuple[str, ...] | None = None) -> tuple[EnterpriseTopic, ...]:
    if not topic_slugs:
        return ENTERPRISE_TOPICS
    wanted = set(topic_slugs)
    return tuple(topic for topic in ENTERPRISE_TOPICS if topic.slug in wanted)


def enterprise_keywords_for_topics(
    topic_slugs: list[str] | tuple[str, ...] | None = None,
    extra_keywords: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    keywords: list[str] = []
    for topic in selected_topics(topic_slugs):
        keywords.extend(topic.keywords)
    keywords.extend(extra_keywords or [])
    return _dedupe(keywords)


def match_enterprise_topics(
    fields: dict[str, Any],
    topic_slugs: list[str] | tuple[str, ...] | None = None,
    extra_keywords: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    labels: list[str] = []
    names: list[str] = []
    matched_keywords: list[str] = []
    matched_fields: dict[str, list[str]] = {}

    for topic in selected_topics(topic_slugs):
        topic_match = match_keywords(fields, topic.keywords)
        if not topic_match["is_match"]:
            continue
        labels.append(topic.slug)
        names.append(topic.name)
        for keyword in topic_match["matched_keywords"]:
            if keyword not in matched_keywords:
                matched_keywords.append(keyword)
        for field, keywords in topic_match["matched_fields"].items():
            matched_fields.setdefault(field, [])
            for keyword in keywords:
                if keyword not in matched_fields[field]:
                    matched_fields[field].append(keyword)

    custom_match = match_keywords(fields, extra_keywords or [])
    if custom_match["is_match"]:
        if "custom" not in labels:
            labels.append("custom")
            names.append("Tùy chỉnh")
        for keyword in custom_match["matched_keywords"]:
            if keyword not in matched_keywords:
                matched_keywords.append(keyword)
        for field, keywords in custom_match["matched_fields"].items():
            matched_fields.setdefault(field, [])
            for keyword in keywords:
                if keyword not in matched_fields[field]:
                    matched_fields[field].append(keyword)

    return {
        "is_match": bool(labels),
        "topic_labels": labels,
        "topic_names": names,
        "matched_keywords": matched_keywords,
        "matched_fields": matched_fields,
    }
