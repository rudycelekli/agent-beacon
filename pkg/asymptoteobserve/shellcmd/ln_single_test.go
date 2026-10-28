package shellcmd

import (
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"testing"
)

func TestLnSingleSourceMatchesNativeDestination(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("requires POSIX ln")
	}
	binary, err := exec.LookPath("ln")
	if err != nil {
		t.Skip("ln unavailable")
	}
	dir := t.TempDir()
	source := filepath.Join(t.TempDir(), "target.txt")
	if err := os.WriteFile(source, []byte("source"), 0o600); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(binary, "-s", source)
	cmd.Dir = dir
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("ln: %v: %s", err, out)
	}
	target, err := os.Readlink(filepath.Join(dir, "target.txt"))
	if err != nil || target != source {
		t.Fatalf("native ln target = %q, %v", target, err)
	}
	commands, err := Parse("ln -s " + source)
	if err != nil {
		t.Fatal(err)
	}
	want := []FileEffect{{Path: "target.txt", Op: OpLink}}
	if got := FileEffects(commands); !reflect.DeepEqual(got, want) {
		t.Fatalf("FileEffects = %v; native ln created target.txt; want %v", got, want)
	}
}
