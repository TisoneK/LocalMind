/**
 * Settings pages. The modal used to stack eleven unrelated sections in one long scroll; they are
 * grouped here into pages behind a left nav (like most settings screens), so each page answers one
 * question and you never scroll past Ollama to find your theme.
 */

export type PageId = 'general' | 'appearance' | 'shortcuts' | 'providers' | 'models' | 'local' | 'agent' | 'terminal';

export interface SettingsPage {
  id: PageId;
  label: string;
  /** One line under the page title. */
  blurb: string;
  group: 'Basics' | 'Models' | 'Agent';
}

export const PAGES: SettingsPage[] = [
  { id: 'general', label: 'General', blurb: 'What LocalMind does when it opens.', group: 'Basics' },
  { id: 'appearance', label: 'Appearance', blurb: 'Theme, mode and tone.', group: 'Basics' },
  { id: 'shortcuts', label: 'Keyboard shortcuts', blurb: 'Keys the app answers to.', group: 'Basics' },
  { id: 'providers', label: 'Providers & keys', blurb: 'Which AI service to use, and the keys to reach it.', group: 'Models' },
  { id: 'models', label: 'Models', blurb: 'The model that answers, and how it reasons.', group: 'Models' },
  { id: 'local', label: 'Local models', blurb: 'Ollama, running on this machine.', group: 'Models' },
  { id: 'agent', label: 'Agent', blurb: 'What the agent may do, and where its installs go.', group: 'Agent' },
  { id: 'terminal', label: 'Terminal', blurb: 'The shell commands run in.', group: 'Agent' },
];

export const GROUPS: SettingsPage['group'][] = ['Basics', 'Models', 'Agent'];

/** Which page each section (by its heading) belongs to. */
export const SECTION_PAGE: Record<string, PageId> = {
  'On Startup': 'general',
  'Chat mode': 'general',
  'Keyboard shortcuts': 'shortcuts',
  Shell: 'terminal',
  Appearance: 'appearance',
  'AI Provider': 'providers',
  'API Keys': 'providers',
  'AI Connections': 'providers',
  Model: 'models',
  Reasoning: 'models',
  'Local model (Ollama)': 'local',
  'Ollama Server URL': 'local',
  Permissions: 'agent',
  'Best-of-N Editor': 'agent',
  'Package installs': 'agent',
};
