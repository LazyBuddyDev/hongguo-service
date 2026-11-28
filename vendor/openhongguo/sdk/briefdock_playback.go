package sdk

import (
	"context"
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"github.com/beilunyang/openhongguo/internal/protocol"
	"github.com/beilunyang/openhongguo/internal/protocol/sign"
	"github.com/beilunyang/openhongguo/sdk/model"
)

// BriefDockPlayback uses one body-signed POST with the existing device only.
func (c *Client) BriefDockPlayback(ctx context.Context, episodeID, quality string) (*model.Playback, error) {
	if !validID(episodeID) {
		return nil, fmt.Errorf("invalid episode ID")
	}
	p, err := c.ensureSearchGuest(ctx)
	if err != nil {
		return nil, err
	}
	pairs := protocol.DeviceQueryPairs(c.identity(p))
	body, err := protocol.PlaybackBody(episodeID)
	if err != nil {
		return nil, err
	}
	query, headers := sign.SignPlaybackPOST("/novel/player/video_model/v1/", pairs, c.clock().UnixMilli(), p.DeviceID, protocol.VersionName, body, nil)
	d := c.deviceOf(p)
	headers["User-Agent"] = fmt.Sprintf("%s/%s (Linux; U; Android %s; zh_CN; %s; Build/%s;tt-ok/3.12.13.20)", protocol.Package, protocol.VersionCode, d.OSVersion, d.Model, d.Build)
	if p.TTReq != "" {
		headers["Cookie"] = guestCookie(p)
	}
	digest := md5.Sum(body)
	headers["x-ss-stub"] = hex.EncodeToString(digest[:])
	headers["Content-Type"] = "application/json; charset=utf-8"
	raw, _, err := c.doRaw(ctx, "POST", "https://api5-normal-sinfonlinea.fqnovel.com/novel/player/video_model/v1/?"+query, headers, body)
	if err != nil {
		return nil, err
	}
	video, err := playerResponseModel(raw, episodeID)
	if err != nil {
		return nil, err
	}
	return parsePlayerModel(video, episodeID, quality)
}

func playerResponseModel(raw []byte, episodeID string) (json.RawMessage, error) {
	var env struct {
		Data map[string]json.RawMessage `json:"data"`
	}
	if json.Unmarshal(raw, &env) != nil {
		return nil, fmt.Errorf("invalid playback response")
	}
	rows := env.Data
	var row struct {
		VideoModel json.RawMessage `json:"video_model"`
	}
	if direct, ok := rows["video_model"]; ok {
		if supplied, ok := rows["video_id"]; ok {
			var returned string
			if json.Unmarshal(supplied, &returned) != nil || returned != episodeID {
				return nil, fmt.Errorf("playback_episode_mismatch")
			}
		}
		row.VideoModel = direct
	} else {
		if nested, ok := rows["video_model_data"]; ok {
			if json.Unmarshal(nested, &rows) != nil {
				return nil, fmt.Errorf("invalid playback response")
			}
		}
		if json.Unmarshal(rows[episodeID], &row) != nil || len(row.VideoModel) == 0 {
			return nil, fmt.Errorf("playback_episode_mismatch")
		}
	}
	if len(row.VideoModel) > 0 && row.VideoModel[0] == '"' {
		var text string
		if json.Unmarshal(row.VideoModel, &text) != nil {
			return nil, fmt.Errorf("invalid playback model")
		}
		row.VideoModel = json.RawMessage(text)
	}
	return row.VideoModel, nil
}

func parsePlayerModel(video json.RawMessage, episodeID, quality string) (*model.Playback, error) {
	wrapped, _ := json.Marshal(map[string]any{"code": 0, "data": map[string]any{"video_model": video}})
	playback, err := protocol.ParsePlaybackForQuality(wrapped, episodeID, quality)
	if err != nil {
		return nil, err
	}
	if playback.Protected {
		return playback, ErrDRMProtected
	}
	return playback, nil
}
