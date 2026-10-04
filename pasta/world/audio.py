"""Default playback device volume/mute through Core Audio (IAudioEndpointVolume).

Lets PASTA set an exact level and *verify* mute state, instead of pressing
media keys blindly as the old implementation did.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, c_float, c_uint, c_void_p
from ctypes.wintypes import BOOL, DWORD

import comtypes
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
E_RENDER, E_MULTIMEDIA = 0, 1


class IAudioEndpointVolume(IUnknown):
    _iid_ = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
    _methods_ = [
        COMMETHOD([], HRESULT, "RegisterControlChangeNotify", (["in"], c_void_p, "pNotify")),
        COMMETHOD([], HRESULT, "UnregisterControlChangeNotify", (["in"], c_void_p, "pNotify")),
        COMMETHOD([], HRESULT, "GetChannelCount", (["out"], POINTER(c_uint), "pnChannelCount")),
        COMMETHOD([], HRESULT, "SetMasterVolumeLevel", (["in"], c_float, "fLevelDB"), (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "SetMasterVolumeLevelScalar", (["in"], c_float, "fLevel"), (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "GetMasterVolumeLevel", (["out"], POINTER(c_float), "pfLevelDB")),
        COMMETHOD([], HRESULT, "GetMasterVolumeLevelScalar", (["out"], POINTER(c_float), "pfLevel")),
        COMMETHOD([], HRESULT, "SetChannelVolumeLevel", (["in"], c_uint, "n"), (["in"], c_float, "f"),
                  (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "SetChannelVolumeLevelScalar", (["in"], c_uint, "n"), (["in"], c_float, "f"),
                  (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "GetChannelVolumeLevel", (["in"], c_uint, "n"), (["out"], POINTER(c_float), "f")),
        COMMETHOD([], HRESULT, "GetChannelVolumeLevelScalar", (["in"], c_uint, "n"), (["out"], POINTER(c_float), "f")),
        COMMETHOD([], HRESULT, "SetMute", (["in"], BOOL, "bMute"), (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "GetMute", (["out"], POINTER(BOOL), "pbMute")),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Activate", (["in"], POINTER(GUID), "iid"), (["in"], DWORD, "dwClsCtx"),
                  (["in"], c_void_p, "pActivationParams"), (["out"], POINTER(POINTER(IUnknown)), "ppInterface")),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], DWORD, "dataFlow"), (["in"], DWORD, "mask"),
                  (["out"], POINTER(c_void_p), "ppDevices")),
        COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], DWORD, "dataFlow"), (["in"], DWORD, "role"),
                  (["out"], POINTER(POINTER(IMMDevice)), "ppEndpoint")),
    ]


def _endpoint() -> IAudioEndpointVolume:
    comtypes.CoInitialize()
    enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_ALL)
    device = enum.GetDefaultAudioEndpoint(E_RENDER, E_MULTIMEDIA)
    unk = device.Activate(ctypes.byref(IAudioEndpointVolume._iid_), comtypes.CLSCTX_ALL, None)
    return unk.QueryInterface(IAudioEndpointVolume)


def get_state() -> tuple[int, bool]:
    """(volume 0..100, muted)."""
    ep = _endpoint()
    return round(ep.GetMasterVolumeLevelScalar() * 100), bool(ep.GetMute())


def set_mute(muted: bool) -> None:
    _endpoint().SetMute(muted, None)


def set_volume(level: int) -> None:
    ep = _endpoint()
    ep.SetMasterVolumeLevelScalar(max(0.0, min(1.0, level / 100.0)), None)
    if level > 0 and ep.GetMute():
        ep.SetMute(False, None)


def step_volume(delta: int) -> int:
    vol, _ = get_state()
    new = max(0, min(100, vol + delta))
    set_volume(new)
    return new
