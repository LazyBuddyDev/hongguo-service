#![cfg_attr(windows, windows_subsystem = "windows")]
use lazybuddy_hongguo_search as search;
use serde::Deserialize;
use serde_json::{Value, json};
use std::io::{self, Read};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    version: u32,
    id: String,
    method: String,
    #[serde(default)]
    args: Arguments,
}
#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct Arguments {
    #[serde(default)]
    query: String,
    #[serde(default = "first_page")]
    page: u32,
}
fn first_page() -> u32 {
    1
}

fn handle(bytes: &[u8]) -> Value {
    let Ok(request) = serde_json::from_slice::<Request>(bytes) else {
        return json!({"version":1,"id":"","ok":false,"error":{"code":"invalid_request"}});
    };
    let error = |code: &str| json!({"version":1,"id":request.id,"ok":false,"error":{"code":code}});
    if request.version != 1 {
        return error("unsupported_version");
    }
    if request.method == "health" {
        return json!({"version":1,"id":request.id,"ok":true,"data":{"service":"hongguo-search"}});
    }
    if request.method != "search" {
        return error("unknown_method");
    }
    let isolated = std::env::var("LAZYBUDDY_INSTANCE").is_ok_and(|value| value != "default");
    let fixture = std::env::var("LAZYBUDDY_SEARCH_URL").ok();
    let allow_real = std::env::var("LAZYBUDDY_SEARCH_REAL").as_deref() == Ok("1");
    let Some(endpoint) = search::search_endpoint(isolated, fixture.as_deref(), allow_real) else {
        return error("network_disabled");
    };
    match search::search(
        &search::client(),
        &endpoint,
        &request.args.query,
        request.args.page,
        &std::sync::atomic::AtomicBool::new(false),
    ) {
        Ok(data) => {
            let mut reply = json!({"version":1,"id":request.id,"ok":true,"data":data});
            if std::env::args().any(|argument| argument == "--private-covers") {
                for (row, item) in reply["data"]["items"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .zip(&data.items)
                {
                    row["_cover"] = json!(item.cover);
                }
            }
            reply
        }
        Err(reason) => {
            json!({"version":1,"id":request.id,"ok":false,"error":{"code":"search_failed","reason":reason}})
        }
    }
}

fn main() -> io::Result<()> {
    let mut input = Vec::new();
    io::stdin().lock().take(65537).read_to_end(&mut input)?;
    let reply = if input.len() > 65536 {
        json!({"version":1,"id":"","ok":false,"error":{"code":"request_too_large"}})
    } else {
        handle(&input)
    };
    serde_json::to_writer(io::stdout(), &reply)?;
    Ok(())
}
