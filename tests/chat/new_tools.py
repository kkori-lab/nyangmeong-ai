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
# 2026-11-27 ② : 8080 백엔드에 설명 없이 있던 카드 3개
NEW_ACTION_WITHOUT_CODES |= {
    "draft_member_nickname_update",
    "draft_member_profile_update",
    "draft_place_bookmark",
}
# 2026-11-27 ③ : 백엔드 #326 (사람 결정 "전부 다 추가"). 삭제 4개는 test_catalog DELETES에도
NEW_READ_WITHOUT_CODES |= {"check_receipt_save"}
NEW_READ |= {"check_receipt_save", "check_expense_duplicates"}
NEW_ACTION_WITHOUT_CODES |= {
    "delete_pet",
    "unlink_caregiver",
    "delete_caregiver_invitation",
    "delete_expenses",
    "draft_notification_settings",
    "mark_service_tutorial_viewed",
}
NEW_ACTION = NEW_ACTION_WITHOUT_CODES | {
    "draft_receipt_checkup",
    "delete_expenses_by_condition",
    "draft_checkup",
    "draft_prescription",
    "draft_repeat_prevention",
    "draft_pet",
}
