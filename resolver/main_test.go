package main

import (
	"context"
	"crypto/md5"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"github.com/beilunyang/openhongguo/adapters/memstore"
	"github.com/beilunyang/openhongguo/sdk"
	"github.com/beilunyang/openhongguo/sdk/model"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

type roundTrip func(*http.Request) (*http.Response, error)

func (f roundTrip) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestDanmakuFollowsEmptyWindowsAndDeduplicates(t *testing.T) {
	item := model.Danmaku{ID: "1", Text: " sample ", OffsetMS: 2400}
	pages := map[string]*model.DanmakuPage{
		"":       {HasMore: true, Cursor: "second"},
		"second": {Items: []model.Danmaku{item}, HasMore: true, Cursor: "third"},
		"third":  {Items: []model.Danmaku{item, {Text: "invalid", OffsetMS: -1}}},
	}
	calls := 0
	items, err := readDanmaku(func(options sdk.DanmakuOptions) (*model.DanmakuPage, error) {
		calls++
		page := pages[options.Cursor]
		if page == nil {
			t.Fatalf("unexpected cursor %q", options.Cursor)
		}
		return page, nil
	})
	if err != nil || calls != 3 || len(items) != 1 || items[0] != (danmakuItem{Text: "sample", OffsetMS: 2400}) {
		t.Fatalf("unexpected timeline %v after %d reads: %v", items, calls, err)
	}
}

func TestDanmakuRouteDoesNotReceiveAccountCookies(t *testing.T) {
	hits := 0
	wire := &transport{cookies: map[string]string{"sessionid": "fixture"}, client: &http.Client{Transport: roundTrip(func(r *http.Request) (*http.Response, error) {
		hits++
		if _, err := r.Cookie("sessionid"); err == nil {
			t.Fatal("account cookie reached comment list")
		}
		return &http.Response{StatusCode: 403, Header: http.Header{}, Body: io.NopCloser(strings.NewReader("{}"))}, nil
	})}}
	ctx := context.Background()
	address := "https://api5-normal-sinfonlinea.fqnovel.com/novel/commentapi/comment/list/123/v1/"
	for _, request := range []*sdk.Request{
		{Method: "GET", URL: address},
		{Method: "POST", URL: strings.Replace(address, "/list/", "/create/", 1)},
	} {
		if _, err := wire.Do(ctx, request); err == nil {
			t.Fatal("unexpected comment endpoint allowed")
		}
	}
	if _, err := wire.Do(ctx, &sdk.Request{Method: "POST", URL: address}); err != nil {
		t.Fatal(err)
	}
	if _, err := wire.Do(ctx, &sdk.Request{Method: "POST", URL: address}); err == nil || hits != 1 {
		t.Fatal("denied comment request was retried")
	}
}

func TestPlayerRequestUsesSameDeviceAndExactEpisode(t *testing.T) {
	for _, shape := range []string{"matching", "mismatched", "no_outer_id"} {
		matching := shape != "mismatched"
		store := memstore.New()
		store.Save(context.Background(), &sdk.DeviceProfile{DeviceID: "12345", InstallID: "12346", TTReq: "fixture"})
		hits := 0
		wire := &transport{cookies: map[string]string{"sessionid": "fixture"}, client: &http.Client{Transport: roundTrip(func(r *http.Request) (*http.Response, error) {
			hits++
			if r.Method != "POST" || r.URL.Host != "api5-normal-sinfonlinea.fqnovel.com" || r.URL.Path != "/novel/player/video_model/v1/" {
				t.Fatal("wrong playback contract")
			}
			q := r.URL.Query()
			if q.Get("device_id") != "12345" || q.Get("iid") != "12346" || q.Get("video_id") != "" {
				t.Fatal("changed device or leaked business query")
			}
			raw, _ := io.ReadAll(r.Body)
			digest := md5.Sum(raw)
			if r.Header.Get("X-SS-STUB") != hex.EncodeToString(digest[:]) || r.Header.Get("X-Medusa") == "" {
				t.Fatal("missing Medusa or body digest mismatch")
			}
			var payload map[string]any
			if json.Unmarshal(raw, &payload) != nil || payload["video_id"] != "12347" {
				t.Fatal("wrong requested episode")
			}
			biz, ok := payload["biz_param"].(map[string]any)
			if !ok || biz["video_platform"] != float64(3) || biz["need_all_video_definition"] != true || biz["video_id_type"] != float64(0) {
				t.Fatal("wrong playback body")
			}
			if r.Header.Get("Content-Encoding") != "" || r.Header.Get("Content-Type") != "application/json; charset=utf-8" || r.Header.Get("X-SS-STUB") == "" {
				t.Fatal("wrong body transport")
			}
			if _, err := r.Cookie("sessionid"); err != nil {
				t.Fatal("missing account context")
			}
			key := "12347"
			if !matching {
				key = "12348"
			}
			model := map[string]any{"video_id": "fixture", "video_duration": 30, "video_list": []any{map[string]any{"main_url": base64.StdEncoding.EncodeToString([]byte("https://fixture.qznovelvod.com/a.mp4")), "definition": "720p", "vwidth": 1280, "vheight": 720}}}
			encodedModel, _ := json.Marshal(model)
			data := map[string]any{"video_id": key, "video_model": string(encodedModel)}
			if shape == "no_outer_id" {
				delete(data, "video_id")
			}
			body, _ := json.Marshal(map[string]any{"code": 0, "data": data})
			return &http.Response{StatusCode: 200, Header: http.Header{}, Body: io.NopCloser(strings.NewReader(string(body)))}, nil
		})}}
		client, err := sdk.NewClient(sdk.Options{Transport: wire, ProfileStore: store, RetryAttempts: 1, DeviceResets: sdk.Int(0)})
		if err != nil {
			t.Fatal(err)
		}
		playback, err := client.BriefDockPlayback(context.Background(), "12347", "720p")
		if matching && (err != nil || playback.EpisodeID != "12347") {
			t.Fatal("expected playback model")
		}
		if !matching && err == nil {
			t.Fatal("accepted a different episode")
		}
		if hits != 1 {
			t.Fatal("registered or retried")
		}
	}
}
func TestCredentialsStayOnApprovedAccountEndpoints(t *testing.T) {
	hits := 0
	wire := &transport{cookies: map[string]string{"sessionid": "own-fixture"}, client: &http.Client{Transport: roundTrip(func(r *http.Request) (*http.Response, error) {
		hits++
		_, err := r.Cookie("sessionid")
		isVideo := strings.HasPrefix(r.URL.Path, "/novel/player/") || (r.URL.Path == "/reading/bookapi/bookshelf/video/info/v1/" || r.URL.Path == "/reading/bookapi/bookshelf/video/update/v1/") || strings.HasPrefix(r.URL.Path, "/reading/bookapi/read_progress/")
		if (err == nil) != isVideo {
			t.Fatal("account cookie crossed endpoint scope")
		}
		return &http.Response{StatusCode: 200, Header: http.Header{}, Body: io.NopCloser(strings.NewReader("{}"))}, nil
	})}}
	for _, address := range []string{"https://log5-applog-lq.fqnovel.com/service/2/device_register/", "https://api5-normal-sinfonlinea.fqnovel.com/novel/player/video_model/v1/"} {
		if _, err := wire.Do(context.Background(), &sdk.Request{Method: "POST", URL: address}); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := wire.Do(context.Background(), &sdk.Request{URL: "https://api5-normal-sinfonlinea.fqnovel.com.evil/novel/player/video_model/v1/"}); err == nil {
		t.Fatal("untrusted destination accepted")
	}
	if _, err := wire.Do(context.Background(), &sdk.Request{Method: "GET", URL: "https://api5-normal-sinfonlinea.fqnovel.com/reading/bookapi/bookshelf/video/info/v1/"}); err != nil {
		t.Fatal(err)
	}
	if _, err := wire.Do(context.Background(), &sdk.Request{Method: "POST", URL: "https://api5-normal-sinfonlinea.fqnovel.com/reading/bookapi/bookshelf/video/info/v1/"}); err == nil {
		t.Fatal("shelf write accepted")
	}
	if _, err := wire.Do(context.Background(), &sdk.Request{Method: "POST", URL: "https://api5-normal-sinfonlinea.fqnovel.com/reading/bookapi/bookshelf/video/update/v1/"}); err != nil {
		t.Fatal(err)
	}
	if _, err := wire.Do(context.Background(), &sdk.Request{Method: "GET", URL: "https://api5-normal-sinfonlinea.fqnovel.com/reading/bookapi/bookshelf/video/update/v1/"}); err == nil {
		t.Fatal("shelf mutation accepted with wrong method")
	}
	for _, call := range []struct{ method, path string }{{"GET", "list"}, {"POST", "upload"}} {
		if _, err := wire.Do(context.Background(), &sdk.Request{Method: call.method, URL: "https://api5-normal-sinfonlinea.fqnovel.com/reading/bookapi/read_progress/" + call.path + "/v1/"}); err != nil {
			t.Fatal(err)
		}
	}
	for _, call := range []struct{ method, path string }{{"POST", "list"}, {"GET", "upload"}, {"POST", "delete"}} {
		if _, err := wire.Do(context.Background(), &sdk.Request{Method: call.method, URL: "https://api5-normal-sinfonlinea.fqnovel.com/reading/bookapi/read_progress/" + call.path + "/v1/"}); err == nil {
			t.Fatal("unapproved progress operation accepted")
		}
	}
	wire.denied = true
	if _, err := wire.Do(context.Background(), &sdk.Request{URL: "https://api5-normal-sinfonlinea.fqnovel.com/novel/player/video_model/v1/"}); err == nil {
		t.Fatal("denied session retried")
	}
	if hits != 6 {
		t.Fatal("unexpected network operation")
	}
}

func TestFavoriteBodyTargetsOnlyOneStringIDAndExplicitOperation(t *testing.T) {
	for _, add := range []bool{false, true} {
		body, err := favoriteBody("7696437705822981182", add, 1700000000123)
		if err != nil {
			t.Fatal(err)
		}
		var value map[string]any
		if json.Unmarshal(body, &value) != nil {
			t.Fatal("invalid body")
		}
		rows := value["update_bookshelf_video_list"].([]any)
		if len(rows) != 1 {
			t.Fatal("must update one series only")
		}
		row := rows[0].(map[string]any)
		expected := float64(1)
		if add {
			expected = 0
		}
		if row["book_id"] != "7696437705822981182" || row["book_type"] != float64(2) || row["video_shelf_operate_type"] != expected {
			t.Fatal("operation or ID changed")
		}
		if !add && row["group_name"] != "" {
			t.Fatal("cancel group must be explicit")
		}
		if value["is_cancelled"] != false {
			t.Fatal("unexpected bulk cancellation")
		}
	}
	if _, err := favoriteBody("https://outside", true, 1); err == nil {
		t.Fatal("invalid ID accepted")
	}
}

type failedBody struct{}

func (failedBody) Read([]byte) (int, error) { return 0, io.ErrUnexpectedEOF }
func (failedBody) Close() error             { return nil }
func TestEmptyBodyDiagnosticDistinguishesReadFailure(t *testing.T) {
	for _, broken := range []bool{false, true} {
		var body io.ReadCloser = io.NopCloser(strings.NewReader(""))
		if broken {
			body = failedBody{}
		}
		wire := &transport{client: &http.Client{Transport: roundTrip(func(*http.Request) (*http.Response, error) {
			return &http.Response{StatusCode: 200, Header: http.Header{}, Body: body}, nil
		})}}
		_, err := wire.Do(context.Background(), &sdk.Request{Method: "GET", URL: "https://api5-normal-sinfonlineb.fqnovel.com/reading/bookapi/video_tab/multi_video_model/v1/"})
		if wire.status != 200 || wire.bytes != 0 || wire.readOK == broken || (err != nil) != broken {
			t.Fatal("empty response diagnostic lost read status")
		}
	}
}

func TestResponseMetadataNeverCopiesSecretHeaders(t *testing.T) {
	response := &http.Response{Proto: "HTTP/2.0", ContentLength: 0, Uncompressed: true, Header: http.Header{
		"Content-Type": []string{"application/json; token=SECRET"}, "Content-Encoding": []string{"SECRET"}, "Set-Cookie": []string{"SECRET"}, "Location": []string{"https://SECRET.invalid/path?token=SECRET"}, "X-Request-Id": []string{"SECRET"}, "Date": []string{time.Now().Add(-2 * time.Minute).UTC().Format(http.TimeFormat)}, "X-Arbitrary": []string{"SECRET"}}}
	value := responseMetadata(response)
	raw, _ := json.Marshal(value)
	if strings.Contains(string(raw), "SECRET") || value["content_type"] != "application/json" || value["content_encoding"] != "other" || value["declared_length"] != int64(0) || value["request_id_present"] != true || value["location_present"] != true {
		t.Fatal("response diagnostic leaked data or lost safe fields")
	}
	delta := value["date_delta_seconds"].(int64)
	if delta < 119 || delta > 122 {
		t.Fatal("server clock difference lost")
	}
}

func TestPlayerCookiesHaveOneValueAndKeepDeviceSession(t *testing.T) {
	wire := &transport{cookies: map[string]string{"passport_csrf_token": "fixture-account", "sessionid": "fixture-session"}, client: &http.Client{Transport: roundTrip(func(request *http.Request) (*http.Response, error) {
		counts := map[string]int{}
		values := map[string]string{}
		for _, cookie := range request.Cookies() {
			counts[cookie.Name]++
			values[cookie.Name] = cookie.Value
		}
		for name, value := range map[string]string{"passport_csrf_token": "fixture-account", "sessionid": "fixture-session", "install_id": "123", "ttreq": "fixture-device"} {
			if counts[name] != 1 || values[name] != value {
				t.Fatal("account cookie shadowed or device session lost")
			}
		}
		return &http.Response{StatusCode: 200, Header: http.Header{}, Body: io.NopCloser(strings.NewReader("{}"))}, nil
	})}}
	_, err := wire.Do(context.Background(), &sdk.Request{Method: "GET", URL: "https://api5-normal-sinfonlineb.fqnovel.com/reading/bookapi/video_tab/multi_video_model/v1/", Headers: map[string]string{"Cookie": "passport_csrf_token=; passport_csrf_token_default=; install_id=123; ttreq=fixture-device"}})
	if err != nil {
		t.Fatal("fixture transport failed")
	}
}
