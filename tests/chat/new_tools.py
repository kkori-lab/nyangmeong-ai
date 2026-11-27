"""2026-11-27 백엔드 새 도구 41개 이름 (test_catalog·test_tools가 같이 쓴다)"""

# 2026-11-27 백엔드 새 도구 41개 (사람 결정 : 다 실어서 측정)
NEW_READ_WITHOUT_CODES = {
    "get_care_mission_progress",
    "get_health_dashboard_widgets",
    "get_service_tutorial",
    "list_terms",
    "get_terms",
    "get_unread_notification_count",
    "list_notifications",
    "get_notification_settings",
    "get_chat_unread_count",
    "get_today_story",
    "get_news",
    "get_lost_report",
    "get_care_recruitment",
    "get_care_match",
    "get_minimum_wage",
    "get_pet_limit",
    "list_main_shortcuts",
    "list_point_ledger_months",
    "get_caregiver_invitation",
    "get_inquiry",
    "list_notices",
    "get_notice",
}
NEW_READ = NEW_READ_WITHOUT_CODES | {"list_checkup_attachments", "list_breeds", "list_inquiries"}
NEW_ACTION_WITHOUT_CODES = {
    "mark_notification_read",
    "mark_all_notifications_read",
    "cancel_last_dose",
    "draft_etc_inspection",
    "end_observation_item",
    "set_representative_pet",
    "draft_caregiver_invitation",
    "cancel_caregiver_invitation",
    "accept_caregiver_invitation",
    "reject_caregiver_invitation",
    "draft_item_purchase",
    "draft_equipped_items",
}
NEW_ACTION = NEW_ACTION_WITHOUT_CODES | {
    "draft_checkup",
    "draft_prescription",
    "draft_repeat_prevention",
    "draft_pet",
}
