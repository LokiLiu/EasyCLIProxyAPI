import { getCurrentLocale, translate } from '../i18n';

export type ClientApiProfile = {
  id: 'openai' | 'claude' | 'gemini';
  name: string;
  description: string;
  baseUrl: string;
  lanUrl: string | null;
};

const safeLocalPort = (port: number) =>
  Number.isInteger(port) && port >= 1 && port <= 65535 ? port : 8317;

export function webUiManagementUrl(port: number, tlsEnabled = false): string {
  const scheme = tlsEnabled ? 'https' : 'http';
  return `${scheme}://127.0.0.1:${safeLocalPort(port)}/management.html#/login`;
}

export function clientApiProfiles(
  port: number,
  lanIpv4?: string | null,
  tlsEnabled = false,
): ClientApiProfile[] {
  const safePort = safeLocalPort(port);
  const scheme = tlsEnabled ? 'https' : 'http';
  const origin = `${scheme}://127.0.0.1:${safePort}`;
  const lanOrigin = lanIpv4?.trim() ? `${scheme}://${lanIpv4.trim()}:${safePort}` : null;

  return [
    {
      id: 'openai',
      name: 'OpenAI',
      description: translate(getCurrentLocale(), 'kernel.access.openaiDescription'),
      baseUrl: `${origin}/v1`,
      lanUrl: lanOrigin ? `${lanOrigin}/v1` : null,
    },
    {
      id: 'claude',
      name: 'Claude',
      description: translate(getCurrentLocale(), 'kernel.access.claudeDescription'),
      baseUrl: origin,
      lanUrl: lanOrigin,
    },
    {
      id: 'gemini',
      name: 'Gemini',
      description: translate(getCurrentLocale(), 'kernel.access.geminiDescription'),
      baseUrl: origin,
      lanUrl: lanOrigin,
    },
  ];
}
