//go:build unix

package dashboard

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/asymptote-labs/agent-beacon/cli/beacon/internal/endpoint/schema"
	"github.com/asymptote-labs/agent-beacon/cli/beacon/internal/testenv"
)

// A shared system log's rotated archives are readable only by the collector that rotated them, so
// an ordinary user's dashboard, scan or doctor reaches the live log and not the history behind it.
// That absence is skipped the way a rotated-away archive already is, rather than failing the whole
// read; a permission error on the live log is still reported.
func TestReadsSkipAnArchiveThisProcessMayNotRead(t *testing.T) {
	testenv.RequirePOSIXFileModes(t)
	if os.Geteuid() == 0 {
		t.Skip("root reads a 0000 file, so the unreadable archive cannot be staged")
	}
	dir := t.TempDir()
	path := filepath.Join(dir, "runtime.jsonl")
	writeTestLog(t, path, testEvent("2026-05-13T01:01:00Z", "cursor", "file.modified", "file", "repo-b"))
	archive := path + ".1"
	writeTestLog(t, archive, testEvent("2026-05-13T01:00:00Z", "cursor", "command.executed", "command", "repo-a"))
	if err := os.Chmod(archive, 0o000); err != nil {
		t.Fatal(err)
	}

	result, err := ReadEvents(path, EventQuery{Limit: 10})
	if err != nil {
		t.Fatalf("ReadEvents returned error: %v", err)
	}
	if result.TotalMatched != 1 || len(result.Events) != 1 {
		t.Fatalf("matched events = total %d len %d, want 1/1 from the live log", result.TotalMatched, len(result.Events))
	}
	if got := result.Events[0].Event.Event.Action; got != "file.modified" {
		t.Fatalf("event action = %s, want the live log's file.modified", got)
	}

	var streamed int
	if err := StreamEvents(path, func(_ schema.Event) error {
		streamed++
		return nil
	}); err != nil {
		t.Fatalf("StreamEvents returned error: %v", err)
	}
	if streamed != 1 {
		t.Fatalf("streamed %d events, want 1", streamed)
	}

	// The live log is never skipped that way: it is the file the read is about.
	if err := os.Chmod(path, 0o000); err != nil {
		t.Fatal(err)
	}
	if _, err := ReadEvents(path, EventQuery{Limit: 10}); err == nil {
		t.Fatal("an unreadable live log must be reported, not skipped")
	}
}
