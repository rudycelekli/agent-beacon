package cmd

import (
	"errors"
	"net/http"
	"path/filepath"
	"testing"

	"github.com/asymptote-labs/agent-beacon/cli/beacon-hooks/internal/logging"
	"github.com/asymptote-labs/agent-beacon/pkg/asymptoteobserve"
	"github.com/asymptote-labs/agent-beacon/pkg/asymptoteobserve/activesession"
	"github.com/asymptote-labs/agent-beacon/pkg/asymptoteobserve/shareauto"
)

type failingTransport struct{ t *testing.T }

func (f failingTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	f.t.Errorf("hook made a network request: %s %s", r.Method, r.URL)
	return nil, errors.New("no network from hooks")
}

// shareAutoHookEnv points the runtime log, the active-session record and the share settings at a
// temp directory, and fails the test on any HTTP request made through the default transport.
func shareAutoHookEnv(t *testing.T, settings *shareauto.Settings) string {
	t.Helper()
	setupHookConfigDirs(t)
	platformFlag = "claude"
	t.Cleanup(func() { platformFlag = "claude" })
	dir := t.TempDir()
	logPath := filepath.Join(dir, "runtime.jsonl")
	t.Setenv("BEACON_ENDPOINT_MODE", "1")
	t.Setenv("BEACON_ENDPOINT_LOG", logPath)
	t.Setenv(activesession.PathEnv, filepath.Join(dir, activesession.FileName))
	settingsPath := filepath.Join(dir, "share.json")
	setShareSettingsPath(t, func() string { return settingsPath })
	if settings != nil {
		if err := shareauto.Save(settingsPath, *settings); err != nil {
			t.Fatal(err)
		}
	}
	prev := http.DefaultTransport
	http.DefaultTransport = failingTransport{t}
	t.Cleanup(func() { http.DefaultTransport = prev })
	return logPath
}

func setShareSettingsPath(t *testing.T, path func() string) {
	t.Helper()
	prev := logging.ShareSettingsPath
	logging.ShareSettingsPath = path
	t.Cleanup(func() { logging.ShareSettingsPath = prev })
}

// setAccountHome stands in for the account's passwd entry, which is where shareauto.HookPath reads
// the home directory and so the only way to point the hooks at a settings file in a test.
func setAccountHome(t *testing.T, home string) {
	t.Helper()
	prev := shareauto.AccountHome
	shareauto.AccountHome = func() (string, error) { return home, nil }
	t.Cleanup(func() { shareauto.AccountHome = prev })
}

func runClaudeSessionHooks(t *testing.T, sessionID string) {
	t.Helper()
	runClaudeSessionHooksIn(t, sessionID, "/work/project")
}

// runClaudeSessionHooksIn is runClaudeSessionHooks for a session working in dir, for the cases
// where the working directory is what is under test.
func runClaudeSessionHooksIn(t *testing.T, sessionID, dir string) {
	t.Helper()
	runHookWithInput(t, runSessionStart, map[string]interface{}{
		"hook_event_name": "SessionStart", "session_id": sessionID, "cwd": dir,
	})
	runHookWithInput(t, runPromptSubmit, map[string]interface{}{
		"hook_event_name": "UserPromptSubmit", "session_id": sessionID, "cwd": dir, "prompt": "hello",
	})
	runHookWithInput(t, runPostTool, map[string]interface{}{
		"hook_event_name": "PostToolUse", "session_id": sessionID, "cwd": dir,
		"tool_name": "Bash", "tool_input": map[string]interface{}{"command": "ls"}, "tool_response": map[string]interface{}{"stdout": "a"},
	})
}

func shareRequests(t *testing.T, logPath string) []map[string]interface{} {
	t.Helper()
	var out []map[string]interface{}
	for _, event := range endpointEvents(t, logPath) {
		if info, _ := event["event"].(map[string]interface{}); info["action"] == asymptoteobserve.ActionShareRequested {
			out = append(out, event)
		}
	}
	return out
}

func TestAutoShareWritesOneRequestPerSession(t *testing.T) {
	logPath := shareAutoHookEnv(t, &shareauto.Settings{Auto: shareauto.Auto{Enabled: true, Visibility: "private"}})
	runClaudeSessionHooks(t, "sess-a")
	runClaudeSessionHooks(t, "sess-a")
	runClaudeSessionHooks(t, "sess-b")

	requests := shareRequests(t, logPath)
	if len(requests) != 2 {
		t.Fatalf("share requests = %d, want one per session", len(requests))
	}
	first := requests[0]
	if got := first["session"].(map[string]interface{})["id"]; got != "sess-a" {
		t.Fatalf("session = %v", got)
	}
	if got := first["share"].(map[string]interface{})["visibility"]; got != "private" {
		t.Fatalf("share.visibility = %v", got)
	}
	info := first["event"].(map[string]interface{})
	if info["fidelity"] != "inferred" || info["category"] != "session" {
		t.Fatalf("event block = %v", info)
	}
	if got := first["harness"].(map[string]interface{})["name"]; got != "claude_code" {
		t.Fatalf("harness = %v", got)
	}
	// It follows the session's first event, which is SessionStart here.
	events := endpointEvents(t, logPath)
	if events[0]["event"].(map[string]interface{})["action"] != "session.started" || events[1]["event"].(map[string]interface{})["action"] != asymptoteobserve.ActionShareRequested {
		t.Fatalf("order: %v then %v", events[0]["event"], events[1]["event"])
	}
}

func TestAutoShareOffWritesNothing(t *testing.T) {
	logPath := shareAutoHookEnv(t, nil)
	runClaudeSessionHooks(t, "sess-a")
	if n := len(shareRequests(t, logPath)); n != 0 {
		t.Fatalf("share requests with auto-share off = %d", n)
	}
	logPath = shareAutoHookEnv(t, &shareauto.Settings{Auto: shareauto.Auto{Enabled: false}})
	runClaudeSessionHooks(t, "sess-c")
	if n := len(shareRequests(t, logPath)); n != 0 {
		t.Fatalf("share requests with auto-share disabled = %d", n)
	}
}

// The hook's environment can come from the repository, so the settings-file override must not point
// it at a file that turns auto-share on.
func TestAutoShareIgnoresRepoSuppliedSettingsPath(t *testing.T) {
	logPath := shareAutoHookEnv(t, nil)
	setShareSettingsPath(t, shareauto.HookPath)
	home := t.TempDir()
	setAccountHome(t, home)
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	override := filepath.Join(t.TempDir(), ".beacon", "user.json")
	if err := shareauto.Save(override, shareauto.Settings{Auto: shareauto.Auto{Enabled: true, Visibility: "public"}}); err != nil {
		t.Fatal(err)
	}
	t.Setenv(shareauto.PathEnv, override)

	runClaudeSessionHooks(t, "sess-a")
	if n := len(shareRequests(t, logPath)); n != 0 {
		t.Fatalf("share requests from a repo-supplied settings file = %d", n)
	}
}

// $HOME is environment too, so a repository that can set it must not be able to choose the file
// that turns auto-share on, with the visibility it chooses.
func TestAutoShareIgnoresRepoSuppliedHome(t *testing.T) {
	logPath := shareAutoHookEnv(t, nil)
	setShareSettingsPath(t, shareauto.HookPath)
	account := t.TempDir()
	setAccountHome(t, account)

	// A clone ships a user file and points $HOME at the checkout that holds it.
	repo := t.TempDir()
	shipped := shareauto.Settings{Auto: shareauto.Auto{Enabled: true, Visibility: "public"}}
	if err := shareauto.Save(filepath.Join(repo, ".beacon", "endpoint", shareauto.FileName), shipped); err != nil {
		t.Fatal(err)
	}
	t.Setenv("HOME", repo)
	t.Setenv("USERPROFILE", repo)
	runClaudeSessionHooksIn(t, "sess-a", repo)
	if n := len(shareRequests(t, logPath)); n != 0 {
		t.Fatalf("share requests from a repo-supplied HOME = %d", n)
	}

	// The same file in the account's own home does apply, so the session above was refused for
	// where its settings came from rather than for auto-share being off.
	if err := shareauto.Save(filepath.Join(account, ".beacon", "endpoint", shareauto.FileName), shipped); err != nil {
		t.Fatal(err)
	}
	runClaudeSessionHooksIn(t, "sess-b", repo)
	requests := shareRequests(t, logPath)
	if len(requests) != 1 {
		t.Fatalf("share requests from the account's own settings = %d, want 1", len(requests))
	}
	if got := requests[0]["session"].(map[string]interface{})["id"]; got != "sess-b" {
		t.Fatalf("share request session = %v, want sess-b", got)
	}
}

func TestAutoShareHonorsProjectOptOut(t *testing.T) {
	logPath := shareAutoHookEnv(t, &shareauto.Settings{
		Auto:     shareauto.Auto{Enabled: true},
		Projects: []shareauto.Project{{Path: "/work/project", Enabled: false}},
	})
	runClaudeSessionHooks(t, "sess-a")
	if n := len(shareRequests(t, logPath)); n != 0 {
		t.Fatalf("share requests in an opted-out project = %d", n)
	}
}
