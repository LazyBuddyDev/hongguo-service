package main

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

type signerClient struct {
	endpoint string
	token    string
	client   *http.Client
}

var signatureHeaders = []string{"X-Gorgon", "X-Helios", "X-Medusa", "X-Khronos", "X-Argus", "X-Ladon"}

func configuredSigner() (*signerClient, error) {
	address := os.Getenv("LAZYBUDDY_HONGGUO_SIGNER_URL")
	if address == "" {
		return nil, nil
	}
	u, err := url.Parse(address)
	if err != nil || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") ||
		(u.Scheme != "https" && !(u.Scheme == "http" && (u.Hostname() == "127.0.0.1" || u.Hostname() == "::1" || u.Hostname() == "localhost"))) {
		return nil, errors.New("signer_configuration_invalid")
	}
	return &signerClient{endpoint: strings.TrimRight(address, "/") + "/feature-hash", token: os.Getenv("LAZYBUDDY_HONGGUO_SIGNER_TOKEN"),
		client: &http.Client{Timeout: 5 * time.Second, Transport: &http.Transport{Proxy: nil}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}, nil
}

func (s *signerClient) sign(ctx context.Context, upstream *http.Request, body []byte) error {
	payload, err := json.Marshal(struct {
		URL  string `json:"url"`
		Body string `json:"body_hex,omitempty"`
	}{upstream.URL.String(), hex.EncodeToString(body)})
	if err != nil {
		return errors.New("signer_request_invalid")
	}
	req, err := http.NewRequestWithContext(ctx, "POST", s.endpoint, bytes.NewReader(payload))
	if err != nil {
		return errors.New("signer_request_invalid")
	}
	req.Header.Set("Content-Type", "application/json")
	if s.token != "" {
		req.Header.Set("X-Signer-Token", s.token)
	}
	resp, err := s.client.Do(req)
	if err != nil {
		return errors.New("signer_unavailable")
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return errors.New("signer_rejected")
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, (64<<10)+1))
	var result struct {
		Headers map[string]string `json:"headers"`
	}
	if err != nil || len(raw) > 64<<10 || json.Unmarshal(raw, &result) != nil {
		return errors.New("signer_response_invalid")
	}
	headers := http.Header{}
	for name, value := range result.Headers {
		headers.Set(name, value)
	}
	for _, name := range signatureHeaders {
		value := headers.Get(name)
		if value == "" || len(value) > 16384 {
			return errors.New("signer_response_invalid")
		}
		for _, c := range value {
			if c < 33 || c > 126 {
				return errors.New("signer_response_invalid")
			}
		}
	}
	for _, name := range signatureHeaders {
		upstream.Header.Set(name, headers.Get(name))
	}
	return nil
}
