import { defineConfig } from 'vitepress'

const repo = 'https://github.com/matinfo/pii-airlock'

export default defineConfig({
  title: 'pii-airlock',
  description: 'Keep real personal data out of your AI prompts. Local, reversible, no cloud.',
  // Served from https://matinfo.github.io/pii-airlock/
  base: '/pii-airlock/',
  cleanUrls: true,
  lastUpdated: true,
  head: [['link', { rel: 'icon', href: '/pii-airlock/logo.svg' }]],

  themeConfig: {
    logo: '/logo.svg',
    nav: [
      { text: 'Get started', link: '/guide/quick-start' },
      { text: 'Use it with…', link: '/use/pick-your-setup' },
      { text: 'Help', link: '/guide/troubleshooting' },
      { text: 'Reference', link: '/reference/commands' },
    ],
    sidebar: [
      {
        text: 'Start here',
        items: [
          { text: 'What is pii-airlock?', link: '/guide/what-is-it' },
          { text: 'Quick start (5 minutes)', link: '/guide/quick-start' },
          { text: 'Install, all options', link: '/guide/install' },
          { text: 'Check that it works', link: '/guide/check-it-works' },
        ],
      },
      {
        text: 'Use it with your tools',
        items: [
          { text: 'Pick your setup', link: '/use/pick-your-setup' },
          { text: 'Claude Code', link: '/use/claude-code' },
          { text: 'GitHub Copilot', link: '/use/copilot' },
          { text: 'Other AI apps and SDKs', link: '/use/gateway' },
          { text: 'Clean a file or some text', link: '/use/files-and-text' },
        ],
      },
      {
        text: 'Make it yours',
        items: [
          { text: 'Tell it what is sensitive', link: '/customize/allow-and-deny' },
          { text: 'Choose what happens', link: '/customize/actions' },
          { text: 'Placeholders explained', link: '/customize/placeholders' },
          { text: 'Add a language', link: '/customize/languages' },
        ],
      },
      {
        text: 'Good to know',
        items: [
          { text: 'Safety and limits', link: '/guide/safety' },
          { text: 'Troubleshooting', link: '/guide/troubleshooting' },
          { text: 'FAQ', link: '/guide/faq' },
        ],
      },
      {
        text: 'Reference',
        items: [
          { text: 'Commands', link: '/reference/commands' },
          { text: 'Settings', link: '/reference/settings' },
          { text: 'What it detects', link: '/reference/detected-types' },
        ],
      },
    ],
    socialLinks: [{ icon: 'github', link: repo }],
    search: { provider: 'local' },
    editLink: {
      pattern: `${repo}/edit/main/docs/:path`,
      text: 'Suggest a change to this page',
    },
    outline: { level: [2, 3], label: 'On this page' },
    footer: {
      message: 'Released under the MIT License.',
      copyright: 'pii-airlock contributors',
    },
  },
})
