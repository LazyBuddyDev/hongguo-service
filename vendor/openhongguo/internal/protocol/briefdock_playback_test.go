package protocol

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestQualityKeepsSupportedCodecAndItsOwnMaterial(t *testing.T) {
	items := []any{
		map[string]any{"main_url": "https://fixture.qznovelvod.com/unsupported", "codec_type": "bytevc2", "definition": "720p", "bitrate": 1, "spade_a": "unsupported-fixture"},
		map[string]any{"main_url": "https://fixture.qznovelvod.com/low", "codec_type": "bytevc1", "definition": "360p", "bitrate": 2, "spade_a": "low-fixture"},
		map[string]any{"main_url": "https://fixture.qznovelvod.com/hd", "video_meta": map[string]any{"codec_type": "bytevc1", "definition": "normal", "vwidth": 1280, "vheight": 720}, "bitrate": 3, "spade_a": "hd-fixture"},
	}
	raw, _ := json.Marshal(map[string]any{"code": 0, "data": map[string]any{"video_model": map[string]any{"video_list": items}}})
	value, err := ParsePlaybackForQuality(raw, "12345", "720p")
	if err != nil || len(value.Streams) != 1 || value.Streams[0].Codec != "bytevc1" || value.KeyMaterial != "hd-fixture" {
		t.Fatal("selected stream and material diverged")
	}
	public, _ := json.Marshal(value)
	if strings.Contains(string(public), "fixture\"") || strings.Contains(string(public), "spade_a") {
		t.Fatal("material leaked into public JSON")
	}
	if _, err := ParsePlaybackForQuality(raw, "12345", "1080p"); err == nil {
		t.Fatal("silently downgraded")
	}
}

func TestHigherCompatibleRenditionKeepsActualResolution(t *testing.T) {
	items := []any{
		map[string]any{"main_url": "https://fixture.qznovelvod.com/new", "codec_type": "bytevc2", "vwidth": 1280, "vheight": 720, "spade_a": "unsupported-fixture"},
		map[string]any{"main_url": "https://fixture.qznovelvod.com/hd", "codec_type": "bytevc1", "vwidth": 1920, "vheight": 1080, "spade_a": "hd-fixture"},
	}
	raw, _ := json.Marshal(map[string]any{"data": map[string]any{"video_model": map[string]any{"video_list": items}}})
	for _, wanted := range []string{"360p", "480p", "720p"} {
		value, err := ParsePlaybackForQuality(raw, "12345", wanted)
		if err != nil || len(value.Streams) != 1 || value.Streams[0].Height != 1080 || value.Streams[0].Definition != "1080p" || value.KeyMaterial != "hd-fixture" {
			t.Fatal("compatible resolution or material was misreported")
		}
	}
}
