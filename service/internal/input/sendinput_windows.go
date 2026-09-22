package input

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net"
	"sync"
	"time"
	"unsafe"

	mlog "github.com/olafnew/mastermice-svc/internal/logging"
	"golang.org/x/sys/windows"
)

// cmdPipe is the connection to the service's command pipe for haptic triggers.
var (
	cmdPipe             net.Conn
	cmdPipeMu           sync.Mutex
	cmdReader           *bufio.Reader
	cmdPartial          []byte
	cmdID               int
	modeShiftConfigured bool
	modeShiftEnabled    bool
)

// SetCmdPipe sets the command pipe connection used for haptic feedback.
func SetCmdPipe(conn net.Conn) {
	cmdPipeMu.Lock()
	cmdPipe = conn
	cmdReader = nil
	cmdPartial = nil
	modeShiftConfigured = false
	if conn != nil {
		cmdReader = bufio.NewReader(conn)
	}
	cmdPipeMu.Unlock()
}

// requestCommand requires cmdPipeMu. Retain buffered bytes and match IDs so a
// delayed reply after a timeout cannot be mistaken for the next command.
func requestCommand(command string, params map[string]interface{}) error {
	if cmdPipe == nil {
		return fmt.Errorf("command pipe unavailable")
	}
	cmdID++
	id := cmdID
	cmdPipe.SetDeadline(time.Now().Add(8 * time.Second))
	defer cmdPipe.SetDeadline(time.Time{})
	if err := json.NewEncoder(cmdPipe).Encode(map[string]interface{}{"id": id, "cmd": command, "params": params}); err != nil {
		return err
	}
	for {
		line, err := cmdReader.ReadBytes('\n')
		cmdPartial = append(cmdPartial, line...)
		if err != nil {
			return err
		}
		var response struct {
			ID    int    `json:"id"`
			OK    bool   `json:"ok"`
			Error string `json:"error"`
		}
		err = json.Unmarshal(cmdPartial, &response)
		cmdPartial = nil
		if err != nil {
			return err
		}
		if response.ID != id {
			continue
		}
		if !response.OK {
			return fmt.Errorf("%s", response.Error)
		}
		return nil
	}
}

// ConfigureModeShift keeps native wheel switching unless the profile maps it.
func ConfigureModeShift(mappings map[string]string) {
	enabled := mappings["mode_shift"] != "" && mappings["mode_shift"] != "none"
	cmdPipeMu.Lock()
	defer cmdPipeMu.Unlock()
	if modeShiftConfigured && modeShiftEnabled == enabled {
		return
	}
	if err := requestCommand("set_mode_shift_divert", map[string]interface{}{"enabled": enabled}); err != nil {
		mlog.Printf("[Spin Mode] Configure failed: %v\n", err)
		return
	}
	modeShiftConfigured, modeShiftEnabled = true, enabled
}

// triggerHaptic sends a haptic pulse via the service command pipe.
// Non-blocking — silently fails if pipe is unavailable.
func triggerHaptic(pulseType int) {
	go func() {
		cmdPipeMu.Lock()
		defer cmdPipeMu.Unlock()
		if cmdPipe == nil {
			return
		}
		if err := requestCommand("haptic_trigger", map[string]interface{}{"pulse_type": pulseType}); err != nil {
			mlog.Printf("[Haptic] Request failed: %v\n", err)
		}
	}()
}

var (
	user32       = windows.NewLazySystemDLL("user32.dll")
	pSendInput   = user32.NewProc("SendInput")
)

const (
	INPUT_KEYBOARD       = 1
	KEYEVENTF_EXTENDEDKEY = 0x0001
	KEYEVENTF_KEYUP       = 0x0002
)

// KEYBDINPUT matches the Windows KEYBDINPUT struct.
type KEYBDINPUT struct {
	Vk        uint16
	Scan      uint16
	Flags     uint32
	Time      uint32
	ExtraInfo uintptr
}

// INPUT matches the Windows INPUT struct (keyboard variant).
type INPUT struct {
	Type uint32
	Ki   KEYBDINPUT
	_    [8]byte // padding to match union size
}

// ExecuteAction looks up an action by ID and injects the key combo via SendInput.
// Returns true if the action was found and executed, false for "none" or unknown.
func ExecuteAction(actionID string) bool {
	if actionID == "cycle_dpi" {
		go func() {
			cmdPipeMu.Lock()
			defer cmdPipeMu.Unlock()
			if err := requestCommand("cycle_dpi", nil); err != nil {
				mlog.Printf("[DPI] Request failed: %v\n", err)
			}
		}()
		return true
	}
	if actionID == "" || actionID == "none" {
		return false
	}

	// Special actions that use DesktopManager (EnumWindows + exact position restore)
	switch actionID {
	case "minimize_all":
		Desktop.MinimizeAll()
		return true
	case "restore_all":
		Desktop.RestoreAll()
		return true
	}

	action, ok := AllActions[actionID]
	if !ok || action.Keys == nil {
		return false
	}

	sendKeyCombo(action.Keys)

	// Haptic feedback on actions (per-event type → pulse type mapping)
	// TODO: make configurable via UI per-event haptic settings
	hapticMap := map[string]int{
		"virtual_desktop_left":  0x04, // Tick
		"virtual_desktop_right": 0x04, // Tick
		"minimize_all":          0x02, // Light
		"restore_all":           0x02, // Light
	}
	if pulse, ok := hapticMap[actionID]; ok {
		triggerHaptic(pulse)
	}

	return true
}

// sendKeyCombo presses all keys simultaneously, holds briefly, then releases in reverse.
// Matches Python's send_key_combo behavior.
func sendKeyCombo(keys []uint16) {
	n := len(keys)
	if n == 0 {
		return
	}

	// Build input array: N key-down + N key-up
	inputs := make([]INPUT, n*2)

	// Key-down events (in order)
	for i, vk := range keys {
		var flags uint32
		if IsExtendedKey(vk) {
			flags |= KEYEVENTF_EXTENDEDKEY
		}
		inputs[i] = INPUT{
			Type: INPUT_KEYBOARD,
			Ki: KEYBDINPUT{
				Vk:    vk,
				Flags: flags,
			},
		}
	}

	// Key-up events (reverse order)
	for i := 0; i < n; i++ {
		vk := keys[n-1-i]
		var flags uint32 = KEYEVENTF_KEYUP
		if IsExtendedKey(vk) {
			flags |= KEYEVENTF_EXTENDEDKEY
		}
		inputs[n+i] = INPUT{
			Type: INPUT_KEYBOARD,
			Ki: KEYBDINPUT{
				Vk:    vk,
				Flags: flags,
			},
		}
	}

	// Send key-down events
	sendInputs(inputs[:n])

	// Brief hold (matches Python's 50ms sleep)
	time.Sleep(50 * time.Millisecond)

	// Send key-up events
	sendInputs(inputs[n:])
}

func sendInputs(inputs []INPUT) {
	if len(inputs) == 0 {
		return
	}
	ret, _, err := pSendInput.Call(
		uintptr(len(inputs)),
		uintptr(unsafe.Pointer(&inputs[0])),
		uintptr(unsafe.Sizeof(inputs[0])),
	)
	if ret == 0 {
		fmt.Printf("[Input] SendInput failed: %v\n", err)
	}
}
