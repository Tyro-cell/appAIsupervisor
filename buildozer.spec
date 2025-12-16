[app]
title = AiSupervisor
package.name = ai_supervisor
package.domain = org.example

source.dir = .
source.include_exts = py,kv,png,jpg,ttf,json,otf,ttc

version = 0.1

requirements = python3,kivy,kivymd,plyer,httpx

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,POST_NOTIFICATIONS,WAKE_LOCK,FOREGROUND_SERVICE
android.api = 34
android.minapi = 24
android.sdk_build_tools = 34.0.0
android.archs = arm64-v8a
android.arch = arm64-v8a

services = reminder:service/main.py

[buildozer]
log_level = 2
