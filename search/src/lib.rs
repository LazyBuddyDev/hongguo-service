//! Anonymous website search. No account cookies, App signatures or local "favorites".
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::HashSet,
    sync::atomic::{AtomicBool, Ordering},
};

pub const SEARCH_URL: &str = "https://hongguoduanju.com/api/search/result";

pub fn search_endpoint(isolated: bool, fixture: Option<&str>, allow_real: bool) -> Option<String> {
    if !isolated {
        return Some(SEARCH_URL.to_owned());
    }
    if let Some(url) = fixture {
        let uri: ureq::http::Uri = url.parse().ok()?;
        return (uri.scheme_str() == Some("http")
            && uri.host() == Some("127.0.0.1")
            && uri.path() == "/api/search/result"
            && uri.query().is_none())
        .then(|| url.to_owned());
    }
    allow_real.then(|| SEARCH_URL.to_owned())
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Drama {
    pub id: String,
    pub title: String,
    pub introduction: String,
    pub episodes: Option<u64>,
    pub url: String,
    #[serde(default, skip_serializing)]
    pub cover: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
pub struct SearchPage {
    pub items: Vec<Drama>,
    pub page: u32,
    pub has_more: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchError {
    InvalidQuery,
    InvalidResponse,
    VerificationRequired,
    Network,
    Http(u16),
    Cancelled,
    NetworkDisabled,
}
impl std::fmt::Display for SearchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            Self::InvalidQuery => "请输入 1–80 个字符的关键词",
            Self::InvalidResponse => "官网结果或分页结构异常，请稍后重试",
            Self::VerificationRequired => "官网拒绝请求或需要验证，请在官网处理后重试",
            Self::Network => "连接官网失败，请稍后重试",
            Self::Http(_) => "官网服务暂不可用，请稍后重试",
            Self::Cancelled => "已暂停搜索",
            Self::NetworkDisabled => "当前实例的搜索服务未启用或配置无效",
        })
    }
}

pub fn query(value: &str) -> Result<&str, SearchError> {
    let value = value.trim();
    if value.is_empty() || value.chars().count() > 80 || value.chars().any(char::is_control) {
        return Err(SearchError::InvalidQuery);
    }
    Ok(value)
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Response {
    search_list: Vec<Value>,
    has_more: bool,
    page_num: u32,
    total_pages: u32,
}
pub fn parse(body: &str, expected: u32) -> Result<SearchPage, SearchError> {
    let response: Response =
        serde_json::from_str(body).map_err(|_| SearchError::InvalidResponse)?;
    if expected == 0
        || response.page_num != expected
        || (response.total_pages != 0 && expected > response.total_pages)
        || (response.has_more && response.search_list.is_empty())
    {
        return Err(SearchError::InvalidResponse);
    }
    let mut seen = HashSet::new();
    let mut items = Vec::new();
    for row in response.search_list {
        let Some(video) = row.get("video_data").filter(|value| value.is_object()) else {
            continue;
        };
        let id = match &video["series_id"] {
            Value::String(id) => id.clone(),
            Value::Number(id) if id.is_u64() => id.to_string(),
            _ => return Err(SearchError::InvalidResponse),
        };
        let title = video["series_title"]
            .as_str()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .ok_or(SearchError::InvalidResponse)?;
        if id.len() > 32
            || !id.bytes().all(|c| c.is_ascii_digit())
            || id.bytes().all(|c| c == b'0')
            || title.chars().count() > 256
        {
            return Err(SearchError::InvalidResponse);
        }
        if !seen.insert(id.clone()) {
            continue;
        }
        items.push(Drama {
            url: format!("https://hongguoduanju.com/detail?series_id={id}"),
            id,
            title: title.to_owned(),
            introduction: video["series_intro"]
                .as_str()
                .unwrap_or_default()
                .trim()
                .chars()
                .take(500)
                .collect(),
            episodes: video["episode_cnt"].as_u64(),
            cover: video["series_cover"]
                .as_str()
                .filter(|u| valid_cover_url(u))
                .map(str::to_owned),
        });
    }
    Ok(SearchPage {
        items,
        page: expected,
        has_more: response.has_more
            && (response.total_pages == 0 || expected < response.total_pages),
    })
}

pub fn search(
    client: &ureq::Agent,
    endpoint: &str,
    keyword: &str,
    page: u32,
    cancelled: &AtomicBool,
) -> Result<SearchPage, SearchError> {
    let keyword = query(keyword)?;
    if page == 0 {
        return Err(SearchError::InvalidQuery);
    }
    let request = || {
        let mut response = client
            .get(endpoint)
            .query("query", keyword)
            .query("page", page.to_string())
            .header("Accept", "application/json")
            .header("Referer", "https://hongguoduanju.com/")
            .call()
            .map_err(|e| match e {
                ureq::Error::StatusCode(403) => SearchError::VerificationRequired,
                ureq::Error::StatusCode(code) => SearchError::Http(code),
                _ => SearchError::Network,
            })?;
        let body = response
            .body_mut()
            .with_config()
            .limit(4 * 1024 * 1024)
            .read_to_string()
            .map_err(|_| SearchError::InvalidResponse)?;
        if cancelled.load(Ordering::Acquire) {
            return Err(SearchError::Cancelled);
        }
        parse(&body, page)
    };
    for attempt in 0..2 {
        if cancelled.load(Ordering::Acquire) {
            return Err(SearchError::Cancelled);
        }
        let result = request();
        if attempt == 0
            && matches!(
                result,
                Err(SearchError::Network | SearchError::Http(500..=599))
            )
        {
            continue;
        }
        return result;
    }
    unreachable!()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn search_access_requires_opt_in_and_keeps_fixtures_fail_closed() {
        assert_eq!(search_endpoint(true, None, false), None);
        assert_eq!(
            search_endpoint(true, None, true).as_deref(),
            Some(SEARCH_URL)
        );
        let fixture = "http://127.0.0.1:9041/api/search/result";
        assert_eq!(
            search_endpoint(true, Some(fixture), false).as_deref(),
            Some(fixture)
        );
        assert_eq!(
            search_endpoint(true, Some(fixture), true).as_deref(),
            Some(fixture)
        );
        for invalid in [
            "http://example.com/api/search/result",
            "https://127.0.0.1/api/search/result",
            "http://127.0.0.1/other",
            "http://127.0.0.1/api/search/result?query=test",
            "",
        ] {
            assert_eq!(search_endpoint(true, Some(invalid), true), None);
        }
        assert_eq!(
            search_endpoint(false, Some("invalid"), false).as_deref(),
            Some(SEARCH_URL)
        );
    }
    #[test]
    #[ignore = "manual anonymous website integration; requires network"]
    fn anonymous_website_search_and_pagination() {
        let client = crate::client();
        let cancelled = AtomicBool::new(false);
        let first = search(&client, SEARCH_URL, "万妖", 1, &cancelled).unwrap();
        assert!(!first.items.is_empty());
        assert!(first.has_more);
        let second = search(&client, SEARCH_URL, "万妖", 2, &cancelled).unwrap();
        assert_eq!(second.page, 2);
        assert!(!second.items.is_empty());
        assert!(
            first.items.iter().chain(&second.items).all(|item| item.url
                == format!("https://hongguoduanju.com/detail?series_id={}", item.id))
        );
    }
    fn page(id: &str) -> SearchPage {
        parse(&format!(r#"{{"searchList":[{{"video_data":{{"series_id":"{id}","series_title":"样例","episode_cnt":12}}}}],"hasMore":true,"pageNum":1,"totalPages":2}}"#), 1).unwrap()
    }
    #[test]
    fn parse_keeps_large_ids_and_rejects_wrong_pages_and_malformed_data() {
        assert_eq!(
            page("7702763145030290457").items[0].id,
            "7702763145030290457"
        );
        assert!(
            parse(
                r#"{"searchList":[],"hasMore":true,"pageNum":2,"totalPages":2}"#,
                1
            )
            .is_err()
        );
        assert!(
            parse(
                r#"{"searchList":[],"hasMore":true,"pageNum":1,"totalPages":2}"#,
                1
            )
            .is_err()
        );
        assert!(parse("{}", 1).is_err());
        assert!(query("\n").is_err());
        assert!(query(&"字".repeat(81)).is_err());
    }
    #[test]
    fn non_video_rows_are_ignored_and_duplicate_ids_are_filtered() {
        let empty=parse(r#"{"searchList":[{"video_data":null},{"actor_data":{}}],"hasMore":false,"pageNum":1,"totalPages":1}"#,1).unwrap();
        assert!(empty.items.is_empty());
        let duplicate=parse(r#"{"searchList":[{"video_data":{"series_id":"123","series_title":"A"}},{"video_data":{"series_id":"123","series_title":"B"}}],"hasMore":false,"pageNum":1,"totalPages":1}"#,1).unwrap();
        assert_eq!(duplicate.items.len(), 1);
    }
}

pub fn valid_cover_url(value: &str) -> bool {
    if value.len() > 2048 {
        return false;
    }
    let Ok(uri) = value.parse::<ureq::http::Uri>() else {
        return false;
    };
    uri.scheme_str() == Some("https")
        && uri.authority().is_some_and(|a| !a.as_str().contains('@'))
        && !value.contains('#')
        && uri.port_u16().is_none_or(|p| p == 443)
        && uri.host().is_some_and(|h| {
            h.ends_with(".byteimg.com")
                || h.ends_with(".pstatp.com")
                || h.ends_with(".fqnovelpic.com")
        })
}

pub fn client() -> ureq::Agent {
    ureq::Agent::config_builder()
        .timeout_global(Some(std::time::Duration::from_secs(5)))
        .user_agent("LazyBuddy/0.1")
        .tls_config(
            ureq::tls::TlsConfig::builder()
                .provider(ureq::tls::TlsProvider::NativeTls)
                .root_certs(ureq::tls::RootCerts::PlatformVerifier)
                .build(),
        )
        .build()
        .into()
}
