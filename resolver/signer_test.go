package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"

	"github.com/beilunyang/openhongguo/sdk"
)

func TestSignerConfiguration(t *testing.T) {
	for _, address := range []string{"http://example.com", "https://user:password@example.com", "https://example.com/?token=secret", "https://example.com/path", "ftp://localhost", "https://example.com/#secret"} {
		t.Setenv("LAZYBUDDY_HONGGUO_SIGNER_URL", address)
		if _, err := configuredSigner(); err == nil {
			t.Fatal("unsafe configuration accepted")
		}
	}
	for _, address := range []string{"http://127.0.0.1:19830", "http://[::1]:19830/", "https://signer.example.com"} {
		t.Setenv("LAZYBUDDY_HONGGUO_SIGNER_URL", address)
		if _, err := configuredSigner(); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("LAZYBUDDY_HONGGUO_SIGNER_URL", "")
	if signer, err := configuredSigner(); signer != nil || err != nil {
		t.Fatal("legacy configuration changed")
	}
}

func TestTransportSignsExactRequestAndIsolatesSecrets(t *testing.T) {
	address := "https://api5-normal-sinfonlinea.fqnovel.com/novel/player/video_model/v1/?device_id=123&iid=456&value=a%20b"
	hits := 0
	signer := &signerClient{endpoint: "http://127.0.0.1:19830/feature-hash", token: "fixture-token"}
	signer.client = &http.Client{Transport: roundTrip(func(r *http.Request) (*http.Response, error) {
		if r.Header.Get("Cookie") != "" || r.Header.Get("X-Signer-Token") != "fixture-token" {
			t.Fatal("signer credentials mixed")
		}
		var payload map[string]string
		if json.NewDecoder(r.Body).Decode(&payload) != nil || payload["url"] != address || payload["body_hex"] != "00ff" || len(payload) != 2 {
			t.Fatal("signed bytes changed")
		}
		headers := map[string]string{"Cookie": "injected", "Host": "injected"}
		for _, name := range signatureHeaders {
			headers[name] = "signed"
		}
		raw, _ := json.Marshal(map[string]any{"headers": headers})
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(string(raw)))}, nil
	})}
	wire := &transport{signer: signer, cookies: map[string]string{"sessionid": "fixture-session"}, client: &http.Client{Transport: roundTrip(func(r *http.Request) (*http.Response, error) {
		hits++
		cookie, err := r.Cookie("sessionid")
		if err != nil || cookie.Value != "fixture-session" || r.Header.Get("X-Signer-Token") != "" || r.URL.String() != address || r.Host == "injected" {
			t.Fatal("upstream credentials or URL changed")
		}
		for _, name := range signatureHeaders {
			if r.Header.Get(name) != "signed" {
				t.Fatal("signature not replaced")
			}
		}
		return &http.Response{StatusCode: 200, Header: http.Header{}, Body: io.NopCloser(strings.NewReader("{}"))}, nil
	})}}
	request := &sdk.Request{Method: "GET", URL: address, Body: []byte{0, 255}, Headers: map[string]string{"X-Gorgon": "old"}}
	if _, err := wire.Do(context.Background(), request); err != nil || hits != 1 {
		t.Fatal(err)
	}
	for _, raw := range []string{`{"headers":{"X-Gorgon":"partial"}}`, `{"headers":{"X-Gorgon":"bad\r\nvalue"}}`, `not json`, strings.Repeat("x", 65537)} {
		signer.client.Transport = roundTrip(func(*http.Request) (*http.Response, error) {
			return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(raw))}, nil
		})
		if _, err := wire.Do(context.Background(), request); err == nil || hits != 1 {
			t.Fatal("invalid signer response reached upstream")
		}
	}
	signer.client.Transport = roundTrip(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 401, Body: io.NopCloser(strings.NewReader("SECRET"))}, nil
	})
	if _, err := wire.Do(context.Background(), request); err == nil || strings.Contains(err.Error(), "SECRET") || hits != 1 {
		t.Fatal("signer failure leaked or fell back")
	}
}
