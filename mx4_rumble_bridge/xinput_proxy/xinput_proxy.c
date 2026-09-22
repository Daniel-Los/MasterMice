#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <xinput.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <stdint.h>
#include <string.h>

/*
 * XInput proxy for games that call XInputSetState directly.
 *
 * Put the resulting xinput1_4.dll next to a game's executable.  The proxy
 * reports successful rumble calls to the game, but does not forward vibration
 * to a physical controller.  It forwards the two motor values over localhost
 * UDP to the Python bridge instead.
 */

static HMODULE real_xinput = NULL;
static SOCKET rumble_socket = INVALID_SOCKET;
static INIT_ONCE init_once = INIT_ONCE_STATIC_INIT;

#ifndef REAL_XINPUT_DLL
#define REAL_XINPUT_DLL L"xinput1_4.dll"
#endif

static BOOL CALLBACK initialize_proxy(PINIT_ONCE once, PVOID parameter, PVOID *context) {
    (void)once;
    (void)parameter;
    (void)context;

    wchar_t system_dir[MAX_PATH];
    UINT n = GetSystemDirectoryW(system_dir, MAX_PATH);
    if (n == 0 || n >= MAX_PATH - 32) {
        return TRUE;
    }

    wcscat_s(system_dir, MAX_PATH, L"\\" REAL_XINPUT_DLL);
    real_xinput = LoadLibraryW(system_dir);

    WSADATA data;
    if (WSAStartup(MAKEWORD(2, 2), &data) == 0) {
        rumble_socket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    }
    return TRUE;
}

static void ensure_initialized(void) {
    InitOnceExecuteOnce(&init_once, initialize_proxy, NULL, NULL);
}

static void send_rumble(DWORD user_index, const XINPUT_VIBRATION *vibration) {
    static const char magic[] = "MX4RMB1";
    unsigned char packet[sizeof(magic) - 1 + 1 + 2 + 2];
    struct sockaddr_in address;
    uint16_t left = vibration ? vibration->wLeftMotorSpeed : 0;
    uint16_t right = vibration ? vibration->wRightMotorSpeed : 0;

    if (rumble_socket == INVALID_SOCKET) {
        return;
    }

    memcpy(packet, magic, sizeof(magic) - 1);
    packet[sizeof(magic) - 1] = (unsigned char)(user_index & 0xff);
    memcpy(packet + sizeof(magic) - 1 + 1, &left, sizeof(left));
    memcpy(packet + sizeof(magic) - 1 + 1 + sizeof(left), &right, sizeof(right));

    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = htons(28765);
    inet_pton(AF_INET, "127.0.0.1", &address.sin_addr);
    sendto(rumble_socket, (const char *)packet, (int)sizeof(packet), 0,
           (const struct sockaddr *)&address, sizeof(address));
}

static FARPROC real_proc(const char *name) {
    ensure_initialized();
    return real_xinput ? GetProcAddress(real_xinput, name) : NULL;
}

__declspec(dllexport) DWORD WINAPI XInputSetState(
    DWORD dwUserIndex, XINPUT_VIBRATION *pVibration) {
    ensure_initialized();
    send_rumble(dwUserIndex, pVibration);
    /* Suppress physical-controller rumble. */
    return ERROR_SUCCESS;
}

__declspec(dllexport) DWORD WINAPI XInputGetState(
    DWORD dwUserIndex, XINPUT_STATE *pState) {
    typedef DWORD (WINAPI *Fn)(DWORD, XINPUT_STATE *);
    Fn fn = (Fn)real_proc("XInputGetState");
    return fn ? fn(dwUserIndex, pState) : ERROR_DEVICE_NOT_CONNECTED;
}

__declspec(dllexport) DWORD WINAPI XInputGetCapabilities(
    DWORD dwUserIndex, DWORD dwFlags, XINPUT_CAPABILITIES *pCapabilities) {
    typedef DWORD (WINAPI *Fn)(DWORD, DWORD, XINPUT_CAPABILITIES *);
    Fn fn = (Fn)real_proc("XInputGetCapabilities");
    return fn ? fn(dwUserIndex, dwFlags, pCapabilities) : ERROR_DEVICE_NOT_CONNECTED;
}

__declspec(dllexport) void WINAPI XInputEnable(BOOL enable) {
    typedef void (WINAPI *Fn)(BOOL);
    Fn fn = (Fn)real_proc("XInputEnable");
    if (fn) fn(enable);
}

__declspec(dllexport) DWORD WINAPI XInputGetBatteryInformation(
    DWORD dwUserIndex, BYTE devType, XINPUT_BATTERY_INFORMATION *pBatteryInformation) {
    typedef DWORD (WINAPI *Fn)(DWORD, BYTE, XINPUT_BATTERY_INFORMATION *);
    Fn fn = (Fn)real_proc("XInputGetBatteryInformation");
    return fn ? fn(dwUserIndex, devType, pBatteryInformation) : ERROR_DEVICE_NOT_CONNECTED;
}

__declspec(dllexport) DWORD WINAPI XInputGetKeystroke(
    DWORD dwUserIndex, DWORD dwReserved, PXINPUT_KEYSTROKE pKeystroke) {
    typedef DWORD (WINAPI *Fn)(DWORD, DWORD, PXINPUT_KEYSTROKE);
    Fn fn = (Fn)real_proc("XInputGetKeystroke");
    return fn ? fn(dwUserIndex, dwReserved, pKeystroke) : ERROR_DEVICE_NOT_CONNECTED;
}
