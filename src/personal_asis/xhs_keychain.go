// Applied to xpzouying/xiaohongshu-mcp v2.5.5 cookies package during local build.
// Credentials move only over anonymous pipes to the project's OS keychain bridge.
package cookies

import (
    "bytes"
    "encoding/json"
    "errors"
    "os"
    "os/exec"
)

type keychainCookie struct{}

func keychainBridge(action string, session *sessionFile) (sessionFile, error) {
    python := os.Getenv("ASIS_XHS_PYTHON")
    if python == "" { return sessionFile{}, errors.New("keychain bridge not configured") }
    request := map[string]any{"action": action}
    if session != nil { request["session"] = session }
    raw, err := json.Marshal(request)
    if err != nil { return sessionFile{}, errors.New("invalid keychain request") }
    cmd := exec.Command(python, "-m", "personal_asis.xhs_credentials")
    cmd.Stdin = bytes.NewReader(raw)
    output, err := cmd.Output()
    if err != nil { return sessionFile{}, errors.New("OS keychain unavailable") }
    var response struct { Session sessionFile `json:"session"` }
    if err := json.Unmarshal(output, &response); err != nil {
        return sessionFile{}, errors.New("invalid keychain bridge response")
    }
    return response.Session, nil
}

func (c *keychainCookie) LoadCookies() ([]byte, error) {
    session, err := keychainBridge("read", nil)
    if err != nil { return nil, err }
    if len(session.Cookies) == 0 { return []byte("[]"), nil }
    return session.Cookies, nil
}

func (c *keychainCookie) SaveCookies(data []byte) error {
    session, err := keychainBridge("read", nil)
    if err != nil { return err }
    session.Version = 2
    session.Cookies = json.RawMessage(data)
    _, err = keychainBridge("write", &session)
    return err
}

func (c *keychainCookie) LoadSeed() int {
    session, err := keychainBridge("read", nil)
    if err != nil { return 0 }
    return session.Seed
}

func (c *keychainCookie) SaveSeed(seed int) error {
    session, err := keychainBridge("read", nil)
    if err != nil { return err }
    session.Version, session.Seed = 2, seed
    _, err = keychainBridge("write", &session)
    return err
}

func (c *keychainCookie) DeleteCookies() error {
    return errors.New("session deletion is disabled by the local read-only adapter")
}
