"""运行时补丁：给 AppSettings 添加 lora_dir 字段（如果不存在）。"""

import sys
import os


def patch_app_settings():
    try:
        from state.app_settings import AppSettings
        from pydantic import Field

        if "lora_dir" not in AppSettings.model_fields:
            AppSettings.model_fields["lora_dir"] = Field(
                default="", validation_alias="loraDir", serialization_alias="loraDir"
            )
            AppSettings.model_rebuild(_force=True)
            print("[PATCH] AppSettings patched: added lora_dir field")
    except Exception as e:
        print(f"[PATCH] AppSettings patch failed: {e}")


patch_app_settings()
