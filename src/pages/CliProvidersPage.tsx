import { useEffect, useMemo, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { open } from '@tauri-apps/plugin-dialog';
import {
  CheckCircle2,
  Copy,
  FolderOpen,
  LoaderCircle,
  RefreshCw,
  Save,
  SquareTerminal,
  Trash2,
} from 'lucide-react';
import { useCoreRuntime, type CoreStatus } from '../coreRuntime';
import { useI18n } from '../i18n';

type CliProviderAccount = {
  id: string;
  label: string;
  provider: 'qoder' | 'kiro';
  prefix: string;
  cliPath: string;
  configDir: string;
  fileName: string;
};

type CliProviderSuggestion = Omit<CliProviderAccount, 'fileName'> & { cliFound: boolean };

type CliProviderSetup = {
  coreInstalled: boolean;
  pluginsAvailable: boolean;
  bridgePath: string;
  accounts: CliProviderAccount[];
  suggestions: CliProviderSuggestion[];
};

type Draft = Omit<CliProviderAccount, 'fileName'>;

const draftsFromSetup = (setup: CliProviderSetup): Record<string, Draft> => (
  setup.suggestions.reduce<Record<string, Draft>>((result, suggestion) => {
    const account = setup.accounts.find((candidate) => candidate.id === suggestion.id);
    result[suggestion.id] = account ?? {
      id: suggestion.id,
      label: suggestion.label,
      provider: suggestion.provider,
      prefix: suggestion.prefix,
      cliPath: suggestion.cliPath,
      configDir: suggestion.configDir,
    };
    return result;
  }, {})
);

export function CliProvidersPage() {
  const { locale } = useI18n();
  const zh = locale.startsWith('zh');
  const { status, publishStatus } = useCoreRuntime();
  const [setup, setSetup] = useState<CliProviderSetup | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState<{ tone: 'success' | 'error'; text: string } | null>(null);

  const load = async () => {
    setBusy('load');
    try {
      const result = await invoke<CliProviderSetup>('get_cli_provider_setup');
      setSetup(result);
      setDrafts(draftsFromSetup(result));
      setNotice(null);
    } catch (error) {
      setNotice({ tone: 'error', text: String(error) });
    } finally {
      setBusy('');
    }
  };

  useEffect(() => { void load(); }, []);

  const configured = useMemo(
    () => new Set(setup?.accounts.map((account) => account.id) ?? []),
    [setup],
  );

  const update = (id: string, key: keyof Draft, value: string) => {
    setDrafts((current) => ({
      ...current,
      [id]: { ...current[id], [key]: value },
    }));
  };

  const choose = async (id: string, target: 'cliPath' | 'configDir') => {
    const selected = await open({
      multiple: false,
      directory: target === 'configDir',
      title: target === 'configDir'
        ? (zh ? '选择独立登录目录' : 'Select an isolated login directory')
        : (zh ? '选择 CLI 可执行文件' : 'Select CLI executable'),
    });
    if (typeof selected === 'string') update(id, target, selected);
  };

  const restartIfRunning = async () => {
    if (!status?.running) return;
    const next = await invoke<CoreStatus>('restart_core_process');
    publishStatus(next);
  };

  const save = async (draft: Draft) => {
    setBusy(draft.id);
    setNotice(null);
    try {
      const result = await invoke<CliProviderSetup>('save_cli_provider_account', {
        account: {
          ...draft,
          configDir: draft.provider === 'qoder' ? draft.configDir : null,
        },
      });
      await restartIfRunning();
      setSetup(result);
      setDrafts(draftsFromSetup(result));
      setNotice({
        tone: 'success',
        text: zh ? `${draft.label} 已保存并启用` : `${draft.label} has been saved and enabled`,
      });
    } catch (error) {
      setNotice({ tone: 'error', text: String(error) });
    } finally {
      setBusy('');
    }
  };

  const remove = async (draft: Draft) => {
    setBusy(`delete:${draft.id}`);
    setNotice(null);
    try {
      const result = await invoke<CliProviderSetup>('delete_cli_provider_account', { id: draft.id });
      await restartIfRunning();
      setSetup(result);
      setDrafts(draftsFromSetup(result));
      setNotice({ tone: 'success', text: zh ? '账户配置已移除' : 'Account configuration removed' });
    } catch (error) {
      setNotice({ tone: 'error', text: String(error) });
    } finally {
      setBusy('');
    }
  };

  const copyLoginCommand = async (draft: Draft) => {
    const command = draft.provider === 'qoder'
      ? `"${draft.cliPath}" --config-dir "${draft.configDir}" login`
      : `"${draft.cliPath}" login`;
    await navigator.clipboard.writeText(command);
    setNotice({ tone: 'success', text: zh ? '登录命令已复制' : 'Login command copied' });
  };

  return (
    <section className="page cli-providers-page">
      <header className="management-header cli-provider-header">
        <div>
          <span>CLI Providers</span>
          <h1>{zh ? 'Qoder 与 Kiro' : 'Qoder & Kiro'}</h1>
        </div>
        <button type="button" className="secondary-button" onClick={() => void load()} disabled={Boolean(busy)}>
          <RefreshCw size={16} className={busy === 'load' ? 'spin' : undefined} aria-hidden="true" />
          {zh ? '刷新' : 'Refresh'}
        </button>
      </header>

      <p className="cli-provider-intro">
        {zh
          ? 'CLIProxyAPI 负责协议、流式、并发和调度；Qoder/Kiro 仅作为已登录的模型凭据。每个 Qoder CLI 使用独立配置目录，因此两个 App 可以登录不同账号。'
          : 'CLIProxyAPI owns protocols, streaming, concurrency, and scheduling. Qoder and Kiro are used only as signed-in model credentials. Each Qoder CLI uses an isolated configuration directory.'}
      </p>

      {notice ? <div className={`inline-notice ${notice.tone}`}>{notice.text}</div> : null}
      {setup && (!setup.coreInstalled || !setup.pluginsAvailable) ? (
        <div className="inline-notice error">
          {zh
            ? '自定义 CLIProxyAPI 内核或 provider 插件尚未安装，请先在“版本管理”安装本应用内置内核。'
            : 'The bundled custom CLIProxyAPI core or provider plugins are missing. Install the bundled core from Version Management first.'}
        </div>
      ) : null}

      <div className="oauth-grid cli-provider-grid">
        {setup?.suggestions.map((suggestion) => {
          const draft = drafts[suggestion.id];
          if (!draft) return null;
          const isConfigured = configured.has(draft.id);
          const saving = busy === draft.id;
          const deleting = busy === `delete:${draft.id}`;
          return (
            <section className="panel oauth-card cli-provider-card" key={draft.id}>
              <div className="provider-title-row">
                <span className="cli-provider-icon"><SquareTerminal size={23} aria-hidden="true" /></span>
                <div>
                  <h2>{draft.label}</h2>
                  <span>{draft.provider === 'qoder' ? `qoder/${draft.prefix}` : 'kiro'}</span>
                </div>
                {isConfigured ? (
                  <span className="state-pill success"><CheckCircle2 size={13} />{zh ? '已配置' : 'Configured'}</span>
                ) : null}
              </div>

              <div className="oauth-card-body cli-provider-fields">
                <label>
                  <span>{zh ? '显示名称' : 'Display name'}</span>
                  <input className="config-dialog-text-input" value={draft.label} onChange={(event) => update(draft.id, 'label', event.currentTarget.value)} />
                </label>
                <label>
                  <span>{zh ? '模型前缀' : 'Model prefix'}</span>
                  <input className="config-dialog-text-input" value={draft.prefix} onChange={(event) => update(draft.id, 'prefix', event.currentTarget.value)} />
                </label>
                <label>
                  <span>CLI</span>
                  <div className="cli-provider-path-row">
                    <input className="config-dialog-text-input" value={draft.cliPath} onChange={(event) => update(draft.id, 'cliPath', event.currentTarget.value)} />
                    <button type="button" className="secondary-button compact-button" onClick={() => void choose(draft.id, 'cliPath')}><FolderOpen size={15} /></button>
                  </div>
                </label>
                {draft.provider === 'qoder' ? (
                  <label>
                    <span>{zh ? '独立登录目录' : 'Isolated login directory'}</span>
                    <div className="cli-provider-path-row">
                      <input className="config-dialog-text-input" value={draft.configDir} onChange={(event) => update(draft.id, 'configDir', event.currentTarget.value)} />
                      <button type="button" className="secondary-button compact-button" onClick={() => void choose(draft.id, 'configDir')}><FolderOpen size={15} /></button>
                    </div>
                  </label>
                ) : null}
                <div className="cli-provider-command">
                  <code>{draft.provider === 'qoder' ? `${draft.cliPath} --config-dir ${draft.configDir} login` : `${draft.cliPath} login`}</code>
                  <button type="button" className="secondary-button compact-button" onClick={() => void copyLoginCommand(draft)}><Copy size={14} />{zh ? '复制登录命令' : 'Copy login command'}</button>
                </div>
              </div>

              <div className="button-row management-card-actions">
                <button type="button" className="primary-button" disabled={Boolean(busy) || !setup.pluginsAvailable} onClick={() => void save(draft)}>
                  {saving ? <LoaderCircle size={16} className="spin" /> : <Save size={16} />}
                  {zh ? '保存并启用' : 'Save & enable'}
                </button>
                {isConfigured ? (
                  <button type="button" className="secondary-button danger-button" disabled={Boolean(busy)} onClick={() => void remove(draft)}>
                    {deleting ? <LoaderCircle size={16} className="spin" /> : <Trash2 size={16} />}
                    {zh ? '移除' : 'Remove'}
                  </button>
                ) : null}
              </div>
            </section>
          );
        })}
      </div>
    </section>
  );
}
