use super::{
    auth_dir_path_for_core, core_install_dir, current_core_config_settings,
    patch_existing_core_config, path_to_string, set_core_yaml_nested_value, yaml_key,
    GuiConfigState,
};
use serde::{Deserialize, Serialize};
use std::{fs, path::PathBuf};

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CliProviderSetup {
    core_installed: bool,
    plugins_available: bool,
    bridge_path: String,
    accounts: Vec<CliProviderAccount>,
    suggestions: Vec<CliProviderSuggestion>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CliProviderAccount {
    id: String,
    label: String,
    provider: String,
    prefix: String,
    cli_path: String,
    config_dir: String,
    file_name: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CliProviderSuggestion {
    id: String,
    label: String,
    provider: String,
    prefix: String,
    cli_path: String,
    config_dir: String,
    cli_found: bool,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SaveCliProviderAccount {
    id: String,
    label: String,
    provider: String,
    prefix: String,
    cli_path: String,
    config_dir: Option<String>,
}

fn provider_plugin_directory() -> Result<PathBuf, String> {
    let os = if cfg!(target_os = "macos") {
        "darwin"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else {
        "linux"
    };
    let arch = if cfg!(target_arch = "aarch64") {
        "arm64"
    } else {
        "amd64"
    };
    Ok(core_install_dir()?.join("plugins").join(os).join(arch))
}

fn bridge_path() -> Result<PathBuf, String> {
    let name = if cfg!(target_os = "windows") {
        "cli-proxy-tool-bridge.exe"
    } else {
        "cli-proxy-tool-bridge"
    };
    Ok(provider_plugin_directory()?.join(name))
}

fn home_path(relative: &str) -> String {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_default()
        .join(relative)
        .to_string_lossy()
        .into_owned()
}

fn agent_gateway_profile_path(profile: &str) -> String {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_default()
        .join("Library/Application Support/Agent Gateway/Qoder Profiles")
        .join(profile)
        .to_string_lossy()
        .into_owned()
}

fn first_existing_file(candidates: &[String]) -> String {
    candidates
        .iter()
        .find(|candidate| PathBuf::from(candidate).is_file())
        .cloned()
        .or_else(|| candidates.first().cloned())
        .unwrap_or_default()
}

fn suggestions() -> Vec<CliProviderSuggestion> {
    let qoder_cli = first_existing_file(&[
        home_path(".qodersec/bin/qodercli"),
        "/Applications/Qoder.app/Contents/Resources/bin/qodercli".to_string(),
        "/Applications/Qoder IDE.app/Contents/Resources/bin/qodercli".to_string(),
    ]);
    let values = vec![
        (
            "qoder",
            "Qoder",
            "qoder",
            "qoder",
            qoder_cli,
            agent_gateway_profile_path("qoder"),
        ),
        (
            "qoderwork",
            "QoderWork",
            "qoder",
            "qoderwork",
            "/Applications/QoderWork.app/Contents/Resources/bin/qodercli".to_string(),
            agent_gateway_profile_path("qoderwork"),
        ),
        (
            "kiro",
            "Kiro",
            "kiro",
            "kiro",
            home_path(".local/bin/kiro-cli"),
            String::new(),
        ),
    ];
    values
        .into_iter()
        .map(
            |(id, label, provider, prefix, cli_path, config_dir)| CliProviderSuggestion {
                id: id.to_string(),
                label: label.to_string(),
                provider: provider.to_string(),
                prefix: prefix.to_string(),
                cli_found: PathBuf::from(&cli_path).is_file(),
                cli_path,
                config_dir,
            },
        )
        .collect()
}

fn account_from_json(file_name: String, value: serde_json::Value) -> Option<CliProviderAccount> {
    let object = value.as_object()?;
    let text = |key: &str| {
        object
            .get(key)
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .trim()
            .to_string()
    };
    let provider = text("type").to_ascii_lowercase();
    if provider != "qoder" && provider != "kiro" {
        return None;
    }
    let mut id = text("id");
    if id.is_empty() {
        id = file_name.trim_end_matches(".json").to_string();
    }
    let mut label = text("label");
    if label.is_empty() {
        label = id.clone();
    }
    Some(CliProviderAccount {
        id,
        label,
        provider,
        prefix: text("prefix"),
        cli_path: text("cli_path"),
        config_dir: text("config_dir"),
        file_name,
    })
}

fn auth_directory(gui_config_state: &GuiConfigState) -> Result<PathBuf, String> {
    let config = gui_config_state.snapshot()?;
    Ok(auth_dir_path_for_core(
        &config.auth_dir,
        &core_install_dir()?,
    ))
}

fn read_accounts(gui_config_state: &GuiConfigState) -> Result<Vec<CliProviderAccount>, String> {
    let directory = auth_directory(gui_config_state)?;
    if !directory.is_dir() {
        return Ok(Vec::new());
    }
    let mut accounts = Vec::new();
    for entry in fs::read_dir(&directory)
        .map_err(|error| format!("读取认证目录失败 {}: {error}", path_to_string(&directory)))?
        .filter_map(Result::ok)
    {
        let path = entry.path();
        let Some(file_name) = path.file_name().and_then(|value| value.to_str()) else {
            continue;
        };
        if !path.is_file() || !file_name.to_ascii_lowercase().ends_with(".json") {
            continue;
        }
        let Ok(raw) = fs::read(&path) else { continue };
        let Ok(value) = serde_json::from_slice::<serde_json::Value>(&raw) else {
            continue;
        };
        if let Some(account) = account_from_json(file_name.to_string(), value) {
            accounts.push(account);
        }
    }
    accounts.sort_by(|left, right| left.id.cmp(&right.id));
    Ok(accounts)
}

#[tauri::command]
pub(crate) fn get_cli_provider_setup(
    gui_config_state: tauri::State<'_, GuiConfigState>,
) -> Result<CliProviderSetup, String> {
    let install_dir = core_install_dir()?;
    let plugin_dir = provider_plugin_directory()?;
    let qoder = plugin_dir.join(if cfg!(target_os = "windows") {
        "qoder.dll"
    } else if cfg!(target_os = "macos") {
        "qoder.dylib"
    } else {
        "qoder.so"
    });
    let kiro = plugin_dir.join(if cfg!(target_os = "windows") {
        "kiro.dll"
    } else if cfg!(target_os = "macos") {
        "kiro.dylib"
    } else {
        "kiro.so"
    });
    let bridge = bridge_path()?;
    Ok(CliProviderSetup {
        core_installed: install_dir.is_dir(),
        plugins_available: qoder.is_file() && kiro.is_file() && bridge.is_file(),
        bridge_path: path_to_string(&bridge),
        accounts: read_accounts(gui_config_state.inner())?,
        suggestions: suggestions(),
    })
}

fn normalized_identifier(value: &str, field: &str) -> Result<String, String> {
    let value = value.trim();
    if value.is_empty()
        || value.len() > 80
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
    {
        return Err(format!("{field} 只能包含字母、数字、点、下划线和连字符"));
    }
    Ok(value.to_ascii_lowercase())
}

fn enable_provider_plugins() -> Result<(), String> {
    patch_existing_core_config(|document| {
        let mut changed = set_core_yaml_nested_value(
            document,
            "plugins",
            "enabled",
            serde_norway::Value::Bool(true),
        )?;
        let root = document
            .as_mapping_mut()
            .ok_or_else(|| "内核配置顶层必须是 YAML 映射".to_string())?;
        let plugins = root
            .entry(yaml_key("plugins"))
            .or_insert_with(|| serde_norway::Value::Mapping(serde_norway::Mapping::new()))
            .as_mapping_mut()
            .ok_or_else(|| "plugins 必须是 YAML 映射".to_string())?;
        let configs = plugins
            .entry(yaml_key("configs"))
            .or_insert_with(|| serde_norway::Value::Mapping(serde_norway::Mapping::new()))
            .as_mapping_mut()
            .ok_or_else(|| "plugins.configs 必须是 YAML 映射".to_string())?;
        for provider in ["qoder", "kiro"] {
            let config = configs
                .entry(yaml_key(provider))
                .or_insert_with(|| serde_norway::Value::Mapping(serde_norway::Mapping::new()))
                .as_mapping_mut()
                .ok_or_else(|| format!("plugins.configs.{provider} 必须是 YAML 映射"))?;
            let enabled = yaml_key("enabled");
            if config.get(&enabled) != Some(&serde_norway::Value::Bool(true)) {
                config.insert(enabled, serde_norway::Value::Bool(true));
                changed = true;
            }
            let priority = yaml_key("priority");
            if !config.contains_key(&priority) {
                config.insert(priority, serde_norway::Value::Number(1.into()));
                changed = true;
            }
        }
        Ok(changed)
    })
}

#[tauri::command]
pub(crate) fn save_cli_provider_account(
    gui_config_state: tauri::State<'_, GuiConfigState>,
    account: SaveCliProviderAccount,
) -> Result<CliProviderSetup, String> {
    let id = normalized_identifier(&account.id, "账户 ID")?;
    let provider = normalized_identifier(&account.provider, "Provider")?;
    if provider != "qoder" && provider != "kiro" {
        return Err("仅支持 qoder 或 kiro provider".to_string());
    }
    let prefix = normalized_identifier(&account.prefix, "模型前缀")?;
    let cli_path = PathBuf::from(account.cli_path.trim());
    if !cli_path.is_absolute() || !cli_path.is_file() {
        return Err(format!("CLI 不存在: {}", path_to_string(&cli_path)));
    }
    let bridge = bridge_path()?;
    if !bridge.is_file() {
        return Err(format!("工具桥接程序不存在: {}", path_to_string(&bridge)));
    }
    let config_dir = account.config_dir.unwrap_or_default().trim().to_string();
    if provider == "qoder" && (config_dir.is_empty() || !PathBuf::from(&config_dir).is_absolute()) {
        return Err("Qoder 配置目录必须是绝对路径".to_string());
    }

    let mut value = serde_json::json!({
        "type": provider,
        "id": id,
        "label": account.label.trim(),
        "prefix": prefix,
        "cli_path": path_to_string(&cli_path),
        "bridge_path": path_to_string(&bridge),
    });
    if !config_dir.is_empty() {
        value["config_dir"] = serde_json::Value::String(config_dir);
    }
    let directory = auth_directory(gui_config_state.inner())?;
    fs::create_dir_all(&directory)
        .map_err(|error| format!("创建认证目录失败 {}: {error}", path_to_string(&directory)))?;
    let destination = directory.join(format!("{id}.json"));
    let temporary = directory.join(format!(".{id}.json.tmp-{}", std::process::id()));
    let raw = serde_json::to_vec_pretty(&value)
        .map_err(|error| format!("序列化账户配置失败: {error}"))?;
    fs::write(&temporary, raw)
        .map_err(|error| format!("写入账户配置失败 {}: {error}", path_to_string(&temporary)))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600))
            .map_err(|error| format!("设置账户配置权限失败: {error}"))?;
    }
    fs::rename(&temporary, &destination).map_err(|error| {
        let _ = fs::remove_file(&temporary);
        format!("保存账户配置失败 {}: {error}", path_to_string(&destination))
    })?;

    enable_provider_plugins()?;
    let mut settings = current_core_config_settings(gui_config_state.inner())?;
    settings.plugins_enabled = true;
    gui_config_state.sync_core_settings(&settings)?;
    get_cli_provider_setup(gui_config_state)
}

#[tauri::command]
pub(crate) fn delete_cli_provider_account(
    gui_config_state: tauri::State<'_, GuiConfigState>,
    id: String,
) -> Result<CliProviderSetup, String> {
    let id = normalized_identifier(&id, "账户 ID")?;
    let path = auth_directory(gui_config_state.inner())?.join(format!("{id}.json"));
    if path.is_file() {
        fs::remove_file(&path)
            .map_err(|error| format!("删除账户配置失败 {}: {error}", path_to_string(&path)))?;
    }
    get_cli_provider_setup(gui_config_state)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_cli_provider_account_without_credentials() {
        let account = account_from_json(
            "qoder.json".to_string(),
            serde_json::json!({
                "type": "qoder",
                "id": "qoder",
                "label": "Qoder personal",
                "prefix": "qoder",
                "cli_path": "/Applications/Qoder.app/Contents/Resources/bin/qodercli",
                "config_dir": "/Users/example/.qoder"
            }),
        )
        .expect("account");
        assert_eq!(account.id, "qoder");
        assert_eq!(account.provider, "qoder");
        assert_eq!(account.prefix, "qoder");
    }

    #[test]
    fn rejects_unsafe_account_identifiers() {
        assert!(normalized_identifier("../qoder", "id").is_err());
        assert_eq!(
            normalized_identifier("Qoder_Work", "id").unwrap(),
            "qoder_work"
        );
    }
}
