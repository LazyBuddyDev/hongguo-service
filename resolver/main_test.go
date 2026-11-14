package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"github.com/beilunyang/openhongguo/adapters/memstore"
	"github.com/beilunyang/openhongguo/sdk"
	"io"
	"net/http"
	"strings"
	"testing"
)

type roundTrip func(*http.Request) (*http.Response, error)

func (f roundTrip) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func TestPlayerRequestUsesSameDeviceAndExactEpisode(t *testing.T) {
	for _, matching := range []bool{true, false} {
		store := memstore.New()
		store.Save(context.Background(), &sdk.DeviceProfile{DeviceID: "12345", InstallID: "12346", TTReq: "fixture"})
		hits := 0
		wire := &transport{cookies: map[string]string{"sessionid": "fixture"}, client: &http.Client{Transport: roundTrip(func(r *http.Request) (*http.Response, error) {
			hits++
			q := r.URL.Query()
			if r.Method != "GET" || r.URL.Host != "api5-normal-sinfonlineb.fqnovel.com" || r.URL.Path != "/reading/bookapi/video_tab/multi_video_model/v1/" || q.Get("video_id") != "12347" || q.Get("device_id") != "12345" || q.Get("iid") != "12346" || q.Get("video_platform") != "1024" || q.Get("ts") != "" {
				t.Fatal("request changed device, episode or route")
			}
			for _, key := range []string{"x-gorgon", "x-helios", "x-medusa", "x-tt-dt"} {
				if r.Header.Get(key) != "" {
					t.Fatal("mixed legacy signatures")
				}
			}
			if len(r.Header.Get("x-argus")) < 100 || len(r.Header.Get("x-ladon")) < 40 {
				t.Fatal("missing full signatures")
			}
			if _, err := r.Cookie("sessionid"); err != nil {
				t.Fatal("missing account context")
			}
			model := map[string]any{"video_id": "fixture", "video_duration": 30, "video_list": []any{map[string]any{"main_url": base64.StdEncoding.EncodeToString([]byte("https://fixture.qznovelvod.com/a.mp4")), "definition": "720p", "vwidth": 1280, "vheight": 720}}}
			key := "12347"
			if !matching {
				key = "12348"
			}
			body, _ := json.Marshal(map[string]any{"code": 0, "data": map[string]any{"video_model_data": map[string]any{key: map[string]any{"video_model": model}}}})
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
		if _, err := wire.Do(context.Background(), &sdk.Request{Method: "POST", URL: "https://api5-normal-sinfonlineb.fqnovel.com/reading/bookapi/video_tab/multi_video_model/v1/"}); err == nil {
			t.Fatal("unexpected player write")
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
