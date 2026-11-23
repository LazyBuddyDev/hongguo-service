// Only private stdin/stdout pipes carry account or media data.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"github.com/beilunyang/openhongguo/adapters/memstore"
	"github.com/beilunyang/openhongguo/sdk"
	"github.com/beilunyang/openhongguo/sdk/model"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

type episode struct {
	ID       string `json:"id"`
	Number   int    `json:"number"`
	Playable bool   `json:"playable"`
}
type watchProgress struct {
	Series   string `json:"series"`
	Item     string `json:"item"`
	Episode  int    `json:"episode"`
	Count    int    `json:"count"`
	Time     int64  `json:"time"`
	Duration int64  `json:"duration"`
	Updated  int64  `json:"updated"`
}
type request struct {
	Favorite *bool              `json:"favorite"`
	Progress *watchProgress     `json:"progress"`
	Mode     string             `json:"mode"`
	Series   string             `json:"series"`
	Episode  int                `json:"episode"`
	Quality  string             `json:"quality"`
	Cookies  map[string]string  `json:"cookies"`
	Profile  *sdk.DeviceProfile `json:"profile"`
	Catalog  []episode          `json:"catalog"`
	Item     string             `json:"item"`
}
type transport struct {
	client       *http.Client
	cookies      map[string]string
	denied       bool
	stage        string
	status       int
	bytes        int
	readOK       bool
	responseMeta map[string]any
}

func (t *transport) Do(ctx context.Context, r *sdk.Request) (*sdk.Response, error) {
	u, err := url.Parse(r.URL)
	if err != nil || u.Scheme != "https" || u.User != nil || u.Fragment != "" || u.Port() != "" || t.denied {
		return nil, errors.New("endpoint_rejected")
	}
	api := u.Host == "api5-normal-sinfonlinea.fqnovel.com" && (u.Path == "/novel/player/video_detail/v1/" || u.Path == "/novel/player/video_model/v1/" || ((u.Path == "/reading/bookapi/bookshelf/video/info/v1/" || u.Path == "/reading/bookapi/read_progress/list/v1/") && r.Method == "GET") || ((u.Path == "/reading/bookapi/read_progress/upload/v1/" || u.Path == "/reading/bookapi/bookshelf/video/update/v1/") && r.Method == "POST"))
	danmaku := u.Host == "api5-normal-sinfonlinea.fqnovel.com" && r.Method == "POST" && danmakuPath.MatchString(u.Path)
	registration := u.Host == "log5-applog-lq.fqnovel.com" && u.Path == "/service/2/device_register/"
	player := u.Host == "api5-normal-sinfonlineb.fqnovel.com" && u.Path == "/reading/bookapi/video_tab/multi_video_model/v1/" && r.Method == "GET"
	if !api && !registration && !player && !danmaku {
		return nil, errors.New("endpoint_rejected")
	}
	t.status, t.bytes, t.readOK = 0, 0, false
	t.responseMeta = nil
	switch u.Path {
	case "/service/2/device_register/":
		t.stage = "registration"
	case "/novel/player/video_detail/v1/":
		t.stage = "catalog"
	case "/novel/player/video_model/v1/":
		t.stage = "playback"
	case "/reading/bookapi/video_tab/multi_video_model/v1/":
		t.stage = "playback"
	}
	req, err := http.NewRequestWithContext(ctx, r.Method, r.URL, bytes.NewReader(r.Body))
	if err != nil {
		return nil, errors.New("request_invalid")
	}
	for k, v := range r.Headers {
		req.Header.Set(k, v)
	}
	if api || player {
		// Replace SDK placeholders by name; appending can send an empty CSRF cookie first.
		merged := map[string]string{}
		for _, cookie := range req.Cookies() {
			merged[cookie.Name] = cookie.Value
		}
		for name, value := range t.cookies {
			merged[name] = value
		}
		req.Header.Del("Cookie")
		names := make([]string, 0, len(merged))
		for name := range merged {
			names = append(names, name)
		}
		sort.Strings(names)
		for _, name := range names {
			req.AddCookie(&http.Cookie{Name: name, Value: merged[name]})
		}
	}
	response, err := t.client.Do(req)
	if err != nil {
		return nil, errors.New("transport_failed")
	}
	defer response.Body.Close()
	t.responseMeta = responseMetadata(response)
	if response.StatusCode == 401 || response.StatusCode == 403 {
		t.denied = true
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, (8<<20)+1))
	t.status, t.bytes, t.readOK = response.StatusCode, len(body), err == nil
	if err != nil || len(body) > 8<<20 {
		return nil, errors.New("response_invalid")
	}

	headers := map[string]string{}
	cookies := map[string]string{}
	for k, v := range response.Header {
		if len(v) > 0 && !strings.EqualFold(k, "Set-Cookie") {
			headers[k] = v[0]
		}
	}
	for _, c := range response.Cookies() {
		cookies[c.Name] = c.Value
	}
	return &sdk.Response{StatusCode: response.StatusCode, Headers: headers, Cookies: cookies, Body: body}, nil
}

// Only categories/numbers/booleans leave the helper; never copy arbitrary header values.
func responseMetadata(response *http.Response) map[string]any {
	category := func(value string, allowed ...string) string {
		value = strings.ToLower(strings.TrimSpace(value))
		if value == "" {
			return "absent"
		}
		for _, candidate := range allowed {
			if value == candidate {
				return value
			}
		}
		return "other"
	}
	contentType := strings.SplitN(response.Header.Get("Content-Type"), ";", 2)[0]
	protocol := category(response.Proto, "http/1.0", "http/1.1", "http/2.0", "http/3.0")
	transfer := "absent"
	if len(response.TransferEncoding) > 0 {
		transfer = category(strings.Join(response.TransferEncoding, ","), "chunked", "identity")
	}
	result := map[string]any{"http_version": protocol, "content_type": category(contentType, "application/json", "application/x-protobuf", "text/html", "application/octet-stream"),
		"content_encoding": category(response.Header.Get("Content-Encoding"), "gzip", "br", "deflate", "identity"), "declared_length": response.ContentLength,
		"uncompressed": response.Uncompressed, "transfer_encoding": transfer, "request_id_present": response.Header.Get("X-Tt-Logid") != "" || response.Header.Get("X-Request-Id") != "", "location_present": response.Header.Get("Location") != ""}
	if stamp, err := http.ParseTime(response.Header.Get("Date")); err == nil {
		delta := int64(time.Since(stamp) / time.Second)
		if delta >= -31536000 && delta <= 31536000 {
			result["date_delta_seconds"] = delta
		}
	}
	return result
}

var id = regexp.MustCompile(`^[1-9][0-9]{0,31}$`)

func favoriteBody(series string, add bool, stamp int64) ([]byte, error) {
	if !id.MatchString(series) || stamp <= 0 {
		return nil, errors.New("invalid_request")
	}
	operation := 1
	if add {
		operation = 0
	}
	entry := map[string]any{"book_id": series, "book_type": 2, "modify_time": stamp, "video_shelf_operate_type": operation}
	if !add {
		entry["group_name"] = ""
	}
	body := map[string]any{"is_cancelled": false, "update_bookshelf_video_list": []any{entry}}
	if add {
		body["shark_extra"] = map[string]string{"enter_from": "MainFragmentActivity", "previous_page": "", "page_list": "MainFragmentActivity", "is_active_behavior": "true", "inactive_type": "0"}
	}
	return json.Marshal(body)
}

var danmakuPath = regexp.MustCompile(`^/novel/commentapi/comment/list/[0-9]{1,32}/v1/$`)

type danmakuItem struct {
	Text     string `json:"text"`
	OffsetMS int64  `json:"offset_ms"`
}

func readDanmaku(list func(sdk.DanmakuOptions) (*model.DanmakuPage, error)) ([]danmakuItem, error) {
	items := []danmakuItem{}
	seen := map[string]bool{}
	var options sdk.DanmakuOptions
	// shortcut: bound one episode read to 32 windows and 1200 comments, load windows on demand if longer episodes need support.
	for range 32 {
		page, err := list(options)
		if err != nil {
			return nil, err
		}
		for _, item := range page.Items {
			content := strings.TrimSpace(item.Text)
			if content == "" || len(content) > 600 || item.OffsetMS < 0 || item.OffsetMS > 86400000 || (item.ID != "" && seen[item.ID]) {
				continue
			}
			if item.ID != "" {
				seen[item.ID] = true
			}
			items = append(items, danmakuItem{Text: content, OffsetMS: item.OffsetMS})
			if len(items) == 1200 {
				return items, nil
			}
		}
		if !page.HasMore || page.Cursor == "" || options.Cursor == page.Cursor {
			break
		}
		options.Cursor = page.Cursor
	}
	return items, nil
}

func resolve(input request) (result map[string]any, err error) {
	if input.Mode == "danmaku" {
		if !id.MatchString(input.Series) || !id.MatchString(input.Item) || len(input.Cookies) != 0 {
			return nil, errors.New("invalid_request")
		}
	} else if input.Mode == "favorite_set" {
		if !id.MatchString(input.Series) || input.Favorite == nil {
			return nil, errors.New("invalid_request")
		}
	} else if input.Mode != "favorites" && input.Mode != "progress_read" && input.Mode != "progress_upload" && (!id.MatchString(input.Series) || input.Episode < 1 || input.Episode > 9999 || (input.Quality != "360p" && input.Quality != "480p" && input.Quality != "720p" && input.Quality != "1080p") || len(input.Catalog) > 9999) {
		return nil, errors.New("invalid_request")
	}
	allowed := map[string]bool{}
	for _, name := range []string{"sessionid", "sessionid_ss", "sid_tt", "uid_tt", "uid_tt_ss", "sid_guard", "passport_csrf_token", "passport_csrf_token_default", "passport_auth_status", "passport_auth_status_ss"} {
		allowed[name] = true
	}
	if (len(input.Cookies) == 0 && input.Mode != "danmaku") || len(input.Cookies) > len(allowed) {
		return nil, errors.New("saved_credentials_missing")
	}
	for name, value := range input.Cookies {
		if !allowed[name] || len(value) == 0 || len(value) > 2048 || strings.ContainsAny(value, "\r\n;\x00") {
			return nil, errors.New("invalid_saved_session")
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	store := memstore.New()
	if input.Profile != nil {
		if err := store.Save(ctx, input.Profile); err != nil {
			return nil, err
		}
	}
	wire := &transport{client: &http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}, cookies: input.Cookies}
	defer func() {
		if err != nil {
			result = map[string]any{"stage": wire.stage, "diagnostic": map[string]any{"stage": wire.stage, "http_status": wire.status, "body_bytes": wire.bytes, "body_read_ok": wire.readOK, "response_meta": wire.responseMeta}}
		}
	}()
	client, err := sdk.NewClient(sdk.Options{Transport: wire, ProfileStore: store, RetryAttempts: 1, DeviceResets: sdk.Int(0)})
	if err != nil {
		return nil, err
	}
	if input.Mode == "danmaku" {
		items, err := readDanmaku(func(options sdk.DanmakuOptions) (*model.DanmakuPage, error) {
			return client.ListDanmaku(ctx, input.Series, input.Item, options)
		})
		if err != nil {
			return nil, err
		}
		return map[string]any{"ok": true, "items": items}, nil
	}
	if input.Mode == "favorites" {
		raw, err := client.BriefDockVideoShelf(ctx)
		if err != nil {
			return nil, err
		}
		var value map[string]json.RawMessage
		if json.Unmarshal(raw, &value) != nil {
			return nil, errors.New("favorites_invalid")
		}
		profile, err := store.Load(ctx)
		if err != nil {
			return nil, err
		}
		return map[string]any{"ok": true, "shelf": json.RawMessage(raw), "profile": profile}, nil
	}
	if input.Mode == "favorite_set" {
		body, err := favoriteBody(input.Series, *input.Favorite, time.Now().UnixMilli())
		if err != nil {
			return nil, err
		}
		raw, err := client.BriefDockUpdateVideoShelf(ctx, body)
		if err != nil {
			return nil, err
		}
		profile, err := store.Load(ctx)
		if err != nil {
			return nil, err
		}
		return map[string]any{"ok": true, "shelf": json.RawMessage(raw), "profile": profile}, nil
	}
	if input.Mode == "progress_read" {
		raw, err := client.BriefDockReadProgress(ctx)
		if err != nil {
			return nil, err
		}
		profile, err := store.Load(ctx)
		if err != nil {
			return nil, err
		}
		return map[string]any{"ok": true, "progress": json.RawMessage(raw), "profile": profile}, nil
	}
	if input.Mode == "progress_upload" {
		p := input.Progress
		if p == nil || !id.MatchString(p.Series) || !id.MatchString(p.Item) || p.Episode < 1 || p.Count < p.Episode || p.Count > 9999 || p.Time < 0 || p.Duration <= 0 || p.Time > p.Duration || p.Duration > 86400000 || p.Updated <= 0 {
			return nil, errors.New("invalid_request")
		}
		entry := map[string]any{"book_id": p.Series, "item_id": p.Item, "vid_index": p.Episode, "episode_count": p.Count, "current_play_time": p.Time, "current_total_time": p.Duration, "read_timestamp_ms": p.Updated, "book_type": 2, "progress_rate": strconv.FormatFloat(float64(p.Time)/float64(p.Duration), 'f', -1, 64), "player_cumulative_total_duration": p.Time}
		body, _ := json.Marshal(map[string]any{"books": []any{entry}, "write_mode": 1})
		raw, err := client.BriefDockUploadProgress(ctx, body)
		if err != nil {
			return nil, err
		}
		profile, err := store.Load(ctx)
		if err != nil {
			return nil, err
		}
		return map[string]any{"ok": true, "progress": json.RawMessage(raw), "profile": profile}, nil
	}
	catalog := input.Catalog
	if len(catalog) == 0 {
		page, err := client.ListEpisodes(ctx, input.Series, sdk.EpisodeOptions{})
		if err != nil {
			return nil, err
		}
		for _, e := range page.Items {
			catalog = append(catalog, episode{ID: e.ID, Number: e.Number, Playable: e.Playable})
		}
	}
	var selected *episode
	for i := range catalog {
		if !id.MatchString(catalog[i].ID) || catalog[i].Number < 1 || catalog[i].Number > 9999 {
			return nil, errors.New("invalid_catalog")
		}
		if catalog[i].Number == input.Episode && catalog[i].Playable {
			selected = &catalog[i]
		}
	}
	if selected == nil {
		return nil, errors.New("episode_unavailable")
	}
	playback, err := client.BriefDockPlayback(ctx, selected.ID, input.Quality)
	if err != nil && !errors.Is(err, sdk.ErrDRMProtected) {
		return nil, err
	}
	if playback == nil {
		return nil, errors.New("media_unavailable")
	}
	if len(playback.Streams) != 1 {
		return nil, errors.New("quality_unavailable")
	}
	stream := playback.Streams[0]
	if stream.Dash || stream.HLS || playback.AudioURL != "" {
		return nil, errors.New("unsupported_media_layout")
	}
	u, err := url.Parse(stream.URL)
	if err != nil || u.Scheme != "https" || !strings.HasSuffix(u.Hostname(), ".qznovelvod.com") || u.User != nil || u.Fragment != "" || (u.Port() != "" && u.Port() != "443") {
		return nil, errors.New("media_source_rejected")
	}
	var key model.ContentKey
	if playback.Protected {
		key, err = sdk.ContentKey(playback)
		if err != nil {
			return nil, errors.New("unsupported_wrapped_material")
		}
	}
	profile, err := store.Load(ctx)
	if err != nil {
		return nil, err
	}
	return map[string]any{"ok": true, "url": stream.URL, "key": key.Hex, "width": stream.Width, "height": stream.Height, "available_qualities": playback.AvailableQualities, "size": stream.Size, "duration": playback.DurationSeconds, "profile": profile, "catalog": catalog}, nil
}
func main() {
	for _, file := range []*os.File{os.Stdin, os.Stdout} {
		info, err := file.Stat()
		if err != nil || info.Mode()&os.ModeNamedPipe == 0 {
			os.Exit(1)
		}
	}
	var input request
	// The caller validates the anonymous-pipe handles and owns the process Job.
	decoder := json.NewDecoder(io.LimitReader(os.Stdin, 65537))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&input); err != nil {
		json.NewEncoder(os.Stdout).Encode(map[string]any{"ok": false, "error": "invalid_request"})
		os.Exit(1)
	}
	result, err := resolve(input)
	if err != nil {
		code := "app_source_unavailable"
		for _, v := range []string{"invalid_request", "invalid_catalog", "saved_credentials_missing", "invalid_saved_session", "episode_unavailable", "quality_unavailable", "unsupported_media_layout", "unsupported_wrapped_material", "media_source_rejected", "playback_episode_mismatch"} {
			if err.Error() == v {
				code = v
			}
		}
		if errors.Is(err, sdk.ErrAuthenticationRequired) {
			code = "app_access_denied"
		}
		if errors.Is(err, sdk.ErrRateLimited) {
			code = "app_rate_limited"
		}
		if errors.Is(err, sdk.ErrTransport) {
			code = "app_source_network_error"
		}
		if errors.Is(err, sdk.ErrAnonymousLimited) {
			code = "app_media_unavailable"
			if stage, ok := result["stage"].(string); ok && (stage == "registration" || stage == "catalog" || stage == "playback") {
				code = "app_" + stage + "_unavailable"
			}
		}
		json.NewEncoder(os.Stdout).Encode(map[string]any{"ok": false, "error": code, "diagnostic": result["diagnostic"]})
		os.Exit(1)
	}
	json.NewEncoder(os.Stdout).Encode(result)
}
