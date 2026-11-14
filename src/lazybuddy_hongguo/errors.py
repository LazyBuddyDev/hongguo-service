"""Stable failure categories; never publish exception text, credentials or addresses."""
MEDIA_CODES={
    'media_redirect_https_required','media_redirect_target_rejected','media_redirect_missing_location','media_redirect_limit',
    'invalid_series','invalid_episode','invalid_quality','saved_credentials_missing','saved_session_verification_failed',
    'app_access_denied','app_media_unavailable','app_registration_unavailable','app_catalog_unavailable',
    'app_playback_unavailable','app_playback_empty_response','app_source_unavailable','app_source_timeout','app_rate_limited','app_source_network_error',
    'episode_unavailable','quality_unavailable','quality_resolution_not_met','media_access_denied','media_redirect_rejected',
    'range_not_supported','media_size_changed','resolver_session_too_large','playback_episode_mismatch','media_network_error',
    'media_http_error','metadata_limit','range_limit','invalid_content_range','incomplete_media_range','unsupported_media_codec',
    'unsupported_protection','unsupported_media_layout','unsupported_top_level_box','media_input_failed','media_network_disabled',
    'login_required','invalid_media_pipe','media_runtime_unavailable','media_not_loaded','media_load_failed',
    'media_seek_failed','media_state_failed','media_request_failed','progress_save_failed','media_close_or_progress_failed',
}


def code(error):
    value=error.args[0] if isinstance(error,ValueError) and error.args else None
    return value if isinstance(value,str) and value in MEDIA_CODES else 'media_request_failed'
