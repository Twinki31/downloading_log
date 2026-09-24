"""Подписи полей. Новые пояснения можно добавлять в LABELS."""
from pathlib import Path

FIELDS = Path(__file__).with_name("log_headers.tsv").read_text().splitlines()
LABELS = {
    "uts": "время события", "ip": "IP-адрес", "referrer": "источник перехода",
    "useragent": "юзерагент", "owner_id": "ID владельца", "site_id": "ID сайта",
    "section_id": "ID раздела", "place_id": "ID площадки размещения",
    "supercampaign_id": "ID суперкампании", "campaign_id": "ID кампании",
    "banner_id": "ID баннера", "banner_template_id": "ID шаблона баннера",
    "advertiser_id": "ID рекламодателя", "event_id": "ID события",
    "flag_virtual": "флаг виртуальности", "duration_ms": "длительность, мс",
    "ya_geo_id": "географический ID", "ya_device_type": "тип устройства",
}
def label(name):
    return f"{name} ({LABELS.get(name, 'описание требует уточнения')})"
