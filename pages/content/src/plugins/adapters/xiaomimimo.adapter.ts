import { BaseAdapterPlugin } from './base.adapter';
import type { AdapterCapability, PluginContext } from '../plugin-types';
import { createLogger } from '@extension/shared/lib/logger';
import { useUIStore } from '../../stores/ui.store';

/**
 * Xiaomi MiMo Adapter for Xiaomi AI Studio (aistudio.xiaomimimo.com)
 *
 * Provides text insertion, form submission and MCP popover injection for
 * Xiaomi's AI Studio chat interface. The chat input is a plain (React
 * controlled) <textarea placeholder="Ask me anything">, so we must use the
 * native value setter to make React notice the change, then fire an input
 * event. Submit is done by clicking the send arrow (found heuristically,
 * multilingual) with an Enter-key fallback.
 */

const logger = createLogger('XiaomiMiMoAdapter');

export class XiaomiMiMoAdapter extends BaseAdapterPlugin {
  readonly name = 'XiaomiMiMoAdapter';
  readonly version = '1.0.0';
  readonly hostnames = ['aistudio.xiaomimimo.com'];
  readonly capabilities: AdapterCapability[] = [
    'text-insertion',
    'form-submission',
    'dom-manipulation'
  ];

  // CSS selectors for Xiaomi AI Studio UI elements.
  // The textarea has no id, so we match by placeholder (multiple languages)
  // and fall back to a generic textarea (there is only one on the page).
  private readonly selectors = {
    CHAT_INPUT: 'textarea[placeholder="Ask me anything"], textarea[placeholder*="Ask"], textarea[placeholder*="Спроси"], textarea[placeholder*="Сообщение"], textarea[placeholder*="Введите"], textarea[placeholder*="\u8f93\u5165"], div[contenteditable="true"], textarea',
    SUBMIT_BUTTON: 'button[type="submit"], button[aria-label*="Send"], button[aria-label*="send"], button[aria-label*="\u53d1\u9001"], button[aria-label*="Отправить"], [data-testid*="send"]',
    MAIN_PANEL: 'main, .chat-container, .conversation, #root'
  };

  // URL tracking
  private lastUrl: string = '';
  private urlCheckInterval: NodeJS.Timeout | null = null;

  // UI integration state
  private mcpPopoverContainer: HTMLElement | null = null;
  private mutationObserver: MutationObserver | null = null;
  private popoverCheckInterval: NodeJS.Timeout | null = null;
  // Shared across ALL adapter instances so the same tool-call Run button is
  // auto-clicked at most once, no matter how many copies of the adapter run.
  // A per-instance memory previously let several copies each click the same
  // re-enabled button, running the tool 3-4 times. [XIAOMI_DEDUP_v2]
  private static autoExecuteIntervalStatic: NodeJS.Timeout | null = null;
  private static readonly clickedExecuteBlocksStatic: Set<string> = new Set();

  private storeEventListenersSetup: boolean = false;
  private domObserversSetup: boolean = false;
  private uiIntegrationSetup: boolean = false;

  private static instanceCount = 0;
  private instanceId: number;

  constructor() {
    super();
    XiaomiMiMoAdapter.instanceCount++;
    this.instanceId = XiaomiMiMoAdapter.instanceCount;
    logger.debug(`Instance #${this.instanceId} created. Total instances: ${XiaomiMiMoAdapter.instanceCount}`);
  }

  async initialize(context: PluginContext): Promise<void> {
    if (this.currentStatus === 'initializing' || this.currentStatus === 'active') {
      this.context?.logger.warn(`Xiaomi adapter instance #${this.instanceId} already initialized or active, skipping`);
      return;
    }
    await super.initialize(context);
    this.context.logger.debug(`Initializing Xiaomi MiMo adapter instance #${this.instanceId}...`);
    this.lastUrl = window.location.href;
    this.setupUrlTracking();
    this.setupStoreEventListeners();
  }

  async activate(): Promise<void> {
    if (this.currentStatus === 'active') {
      this.context?.logger.warn(`Xiaomi adapter instance #${this.instanceId} already active, skipping`);
      return;
    }
    await super.activate();
    this.context.logger.debug(`Activating Xiaomi MiMo adapter instance #${this.instanceId}...`);
    this.setupDOMObservers();
    this.setupUIIntegration();
    // Ensure the automation service is up so that auto-execute (auto-click Run),
    // auto-insert and auto-submit work even if the global app init bailed early.
    void this.ensureAutomationService();
    // Reliable, site-local auto-execute: watch for Run buttons and click them
    // ourselves when the user enabled "Execute". Independent of the renderer's
    // fragile one-shot timing and the cross-world window flag.
    this.setupAutoExecuteWatcher();
    this.context.eventBus.emit('adapter:activated', {
      pluginName: this.name,
      timestamp: Date.now()
    });
  }

  /**
   * Make sure the AutomationService singleton is initialized and the current
   * automation state (autoInsert/autoSubmit/autoExecute) is exposed on the
   * window object that the function-call renderer reads. Safe to call multiple
   * times (initialize() is idempotent).
   */
  private async ensureAutomationService(): Promise<void> {
    try {
      const mod = await import('../../services/automation.service');
      const svc = mod.automationService || mod.default;
      if (svc) {
        await svc.initialize();
        await svc.updateAutomationStateOnWindow();
        this.context.logger.debug('AutomationService ensured and automation state exposed to window');
      }
    } catch (error) {
      this.context.logger.warn('Failed to ensure AutomationService:', error);
    }
  }

  /**
   * Site-local auto-execute watcher.
   *
   * The shared renderer decides whether to auto-click a tool-call's "Run"
   * button only once, at the exact frame the button is first created, and it
   * reads a window flag that lives in the content-script's isolated world.
   * That proved fragile and did not fire on Xiaomi. To make auto-execute
   * reliable we poll for completed tool-call cards (a card is complete once its
   * ".execute-button" exists) and click Run ourselves, but only when the user
   * has turned on the "Execute" toggle. Each block is clicked at most once.
   */
  private setupAutoExecuteWatcher(): void {
    // One shared watcher across ALL adapter instances. Several instances each
    // running their own watcher with their own dedup memory was causing the
    // same tool to run 3-4 times: the Run button re-enables itself after each
    // run, so the next instance would see an enabled button and click again.
    // [XIAOMI_DEDUP_v2]
    if (XiaomiMiMoAdapter.autoExecuteIntervalStatic) {
      this.context.logger.debug('Xiaomi auto-execute watcher already running (shared singleton); skipping');
      return;
    }
    const POLL_MS = 700;
    const MARK_ATTR = 'data-mcp-xiaomi-autoclicked';
    XiaomiMiMoAdapter.autoExecuteIntervalStatic = setInterval(() => {
      try {
        const prefs = useUIStore.getState().preferences;
        if (!prefs || prefs.autoExecute !== true) return;
        const delayMs = Math.max(0, (prefs.autoExecuteDelay || 0) * 1000);
        const blocks = document.querySelectorAll<HTMLDivElement>('.function-block[data-block-id]');
        blocks.forEach(block => {
          const blockId = block.getAttribute('data-block-id');
          if (!blockId) return;
          // Global dedup: a DOM marker on the card itself (visible to every
          // adapter copy AND to separate content-script injections) plus a
          // shared static set.
          if (block.getAttribute(MARK_ATTR) === '1' || XiaomiMiMoAdapter.clickedExecuteBlocksStatic.has(blockId)) return;
          // Skip cards already executed by anyone (results/history present).
          if (block.querySelector('.function-history-panel')) {
            block.setAttribute(MARK_ATTR, '1');
            XiaomiMiMoAdapter.clickedExecuteBlocksStatic.add(blockId);
            return;
          }
          const button = block.querySelector<HTMLButtonElement>('.execute-button');
          // The Run button only exists once the card has fully rendered.
          if (!button || button.disabled) return;
          // Claim this card immediately. The DOM marker is shared, so no other
          // copy will click it again even after the button re-enables.
          block.setAttribute(MARK_ATTR, '1');
          XiaomiMiMoAdapter.clickedExecuteBlocksStatic.add(blockId);
          setTimeout(() => {
            try {
              if (useUIStore.getState().preferences.autoExecute !== true) return;
              const liveBlock =
                document.querySelector<HTMLDivElement>(`.function-block[data-block-id="${blockId}"]`) || block;
              // Re-check it wasn't executed in the meantime.
              if (liveBlock.querySelector('.function-history-panel')) return;
              const liveButton = liveBlock.querySelector<HTMLButtonElement>('.execute-button');
              if (liveButton && !liveButton.disabled) {
                this.context.logger.debug(`Auto-execute (Xiaomi shared watcher): clicking Run once for block ${blockId} [XIAOMI_DEDUP_v2]`);
                liveButton.click();
              }
            } catch (err) {
              this.context.logger.warn('Auto-execute watcher click failed:', err);
            }
          }, delayMs);
        });
      } catch (err) {
        this.context.logger.warn('Auto-execute watcher iteration failed:', err);
      }
    }, POLL_MS);
    this.context.logger.debug('Xiaomi auto-execute watcher started (shared singleton) [XIAOMI_DEDUP_v2]');
  }

  private cleanupAutoExecuteWatcher(): void {
    if (XiaomiMiMoAdapter.autoExecuteIntervalStatic) {
      clearInterval(XiaomiMiMoAdapter.autoExecuteIntervalStatic);
      XiaomiMiMoAdapter.autoExecuteIntervalStatic = null;
    }
    XiaomiMiMoAdapter.clickedExecuteBlocksStatic.clear();
  }

  async deactivate(): Promise<void> {
    if (this.currentStatus === 'inactive' || this.currentStatus === 'disabled') {
      this.context?.logger.warn('Xiaomi adapter already inactive, skipping deactivation');
      return;
    }
    await super.deactivate();
    this.context.logger.debug('Deactivating Xiaomi MiMo adapter...');
    this.cleanupUIIntegration();
    this.cleanupDOMObservers();
    this.cleanupAutoExecuteWatcher();
    this.storeEventListenersSetup = false;
    this.domObserversSetup = false;
    this.uiIntegrationSetup = false;
    this.context.eventBus.emit('adapter:deactivated', {
      pluginName: this.name,
      timestamp: Date.now()
    });
  }

  async cleanup(): Promise<void> {
    await super.cleanup();
    this.context.logger.debug('Cleaning up Xiaomi MiMo adapter...');
    if (this.urlCheckInterval) {
      clearInterval(this.urlCheckInterval);
      this.urlCheckInterval = null;
    }
    if (this.popoverCheckInterval) {
      clearInterval(this.popoverCheckInterval);
      this.popoverCheckInterval = null;
    }
    this.cleanupAutoExecuteWatcher();
    this.cleanupUIIntegration();
    this.cleanupDOMObservers();
    this.storeEventListenersSetup = false;
    this.domObserversSetup = false;
    this.uiIntegrationSetup = false;
  }

  /**
   * Set the value of a (React controlled) input/textarea using the native
   * value setter so that React's onChange handler fires correctly.
   */
  private setNativeValue(element: HTMLTextAreaElement | HTMLInputElement, value: string): void {
    const proto = element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
    if (descriptor && descriptor.set) {
      descriptor.set.call(element, value);
    } else {
      (element as any).value = value;
    }
  }

  /**
   * Insert text into the Xiaomi chat input field.
   */
  async insertText(text: string, options?: { targetElement?: HTMLElement }): Promise<boolean> {
    this.context.logger.debug(`Attempting to insert text into Xiaomi chat input: ${text.substring(0, 50)}${text.length > 50 ? '...' : ''}`);

    const targetElement = options?.targetElement || this.findChatInputElement();

    if (!targetElement) {
      this.context.logger.error('Could not find Xiaomi chat input element');
      this.emitExecutionFailed('insertText', 'Chat input element not found');
      return false;
    }

    try {
      targetElement.focus();

      if (targetElement.tagName === 'TEXTAREA' || targetElement.tagName === 'INPUT') {
        const field = targetElement as HTMLTextAreaElement;
        const currentText = field.value;
        const newContent = currentText ? currentText + '\n\n' + text : text;

        // React-compatible value update via native setter.
        this.setNativeValue(field, newContent);
        try {
          field.selectionStart = field.selectionEnd = field.value.length;
        } catch (e) {
          // some inputs disallow selection manipulation; ignore
        }

        field.dispatchEvent(new InputEvent('input', { bubbles: true }));
        field.dispatchEvent(new Event('change', { bubbles: true }));

        this.context.logger.debug(`Text inserted into textarea. Original: ${currentText.length}, Added: ${text.length}, Total: ${newContent.length}`);
      } else if (targetElement.getAttribute('contenteditable') === 'true') {
        // Fallback for a contenteditable editor.
        targetElement.focus();
        const selection = window.getSelection();
        selection?.removeAllRanges();
        const range = document.createRange();
        range.selectNodeContents(targetElement);
        range.collapse(false);
        selection?.addRange(range);
        if ((targetElement.textContent || '').trim() !== '') {
          document.execCommand('insertText', false, '\n\n');
        }
        document.execCommand('insertText', false, text);
        targetElement.dispatchEvent(new InputEvent('input', { bubbles: true }));
        targetElement.dispatchEvent(new Event('change', { bubbles: true }));
        this.context.logger.debug('Text inserted into contenteditable editor');
      } else {
        const originalValue = (targetElement as any).value || targetElement.textContent || '';
        const newContent = originalValue ? originalValue + '\n\n' + text : text;
        if ('value' in targetElement) {
          (targetElement as any).value = newContent;
        } else {
          targetElement.textContent = newContent;
        }
        targetElement.dispatchEvent(new InputEvent('input', { bubbles: true }));
        targetElement.dispatchEvent(new Event('change', { bubbles: true }));
        this.context.logger.debug('Text inserted using fallback method');
      }

      this.emitExecutionCompleted('insertText', { text }, {
        success: true,
        targetElementType: targetElement.tagName,
        insertedLength: text.length
      });
      return true;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      this.context.logger.error(`Error inserting text into Xiaomi chat input: ${errorMessage}`);
      this.emitExecutionFailed('insertText', errorMessage);
      return false;
    }
  }

  /**
   * Submit the current text. Clicks the send button as soon as it becomes
   * enabled; falls back to pressing Enter. Never clicks the action button while
   * it is in its "Stop" (generating) state, and never both clicks and presses
   * Enter for the same submission.
   */
  async submitForm(options?: { formElement?: HTMLFormElement }): Promise<boolean> {
    this.context.logger.debug('Attempting to submit Xiaomi chat input [XIAOMI_STOPGUARD_v1]');

    return new Promise<boolean>((resolve) => {
      const maxWaitTime = 8000;
      const checkInterval = 250;
      let elapsed = 0;
      let finished = false;

      const finish = (value: boolean): void => {
        if (finished) return;
        finished = true;
        resolve(value);
      };

      const tryOnce = (): boolean => {
        // If the action button is currently a "Stop" button, generation is
        // already running (the message was sent). Clicking it would abort the
        // response, so treat this as "already submitted" and do nothing.
        if (this.findStopButton()) {
          this.context.logger.debug('Xiaomi action button is in "Stop" state; assuming already submitted, not clicking');
          this.emitExecutionCompleted('submitForm', {
            formElement: options?.formElement?.tagName || 'unknown'
          }, { success: true, method: 'already-generating' });
          finish(true);
          return true;
        }

        const button = this.findSubmitButton();
        if (button) {
          const isDisabled =
            (button as HTMLButtonElement).disabled ||
            button.getAttribute('disabled') !== null ||
            button.getAttribute('aria-disabled') === 'true' ||
            button.classList.contains('disabled');

          const rect = button.getBoundingClientRect();
          const isVisible = rect.width > 0 && rect.height > 0;

          if (!isDisabled && isVisible) {
            try {
              button.click();
              this.emitExecutionCompleted('submitForm', {
                formElement: options?.formElement?.tagName || 'unknown'
              }, { success: true, method: 'submitButton.click' });
              this.context.logger.debug('Xiaomi submitted via submit button click');
              finish(true);
              return true;
            } catch (error) {
              this.context.logger.warn('Error clicking submit button, will retry/fallback:', error);
            }
          }
        }
        return false;
      };

      if (tryOnce()) return;

      const intervalId = setInterval(() => {
        elapsed += checkInterval;
        if (tryOnce()) {
          clearInterval(intervalId);
          return;
        }
        if (elapsed >= maxWaitTime) {
          clearInterval(intervalId);
          this.context.logger.warn('Submit button not clickable in time, falling back to Enter key');
          this.tryEnterKeySubmission().then(finish).catch(() => finish(false));
        }
      }, checkInterval);
    });
  }

  private findChatInputElement(): HTMLElement | null {
    const selectors = this.selectors.CHAT_INPUT.split(',');
    for (const selector of selectors) {
      const el = document.querySelector(selector.trim()) as HTMLElement | null;
      if (el) return el;
    }
    return null;
  }

  /**
   * Find the send button: first by known selectors (multilingual aria-label,
   * data-testid, type=submit), then heuristically as the right-most clickable
   * button with an svg icon near the input. Buttons currently in their "Stop"
   * (generating) state are never returned as the send button.
   */
  private findSubmitButton(): HTMLElement | null {
    const directSelectors = this.selectors.SUBMIT_BUTTON.split(',');
    for (const selector of directSelectors) {
      const el = document.querySelector(selector.trim()) as HTMLElement | null;
      if (el && !el.closest('#mcp-popover-container') && !this.isStopButton(el)) {
        this.context.logger.debug(`Found submit button via selector: ${selector.trim()}`);
        return el;
      }
    }

    const input = this.findChatInputElement();
    if (input) {
      let scope: HTMLElement | null = input;
      for (let i = 0; i < 5 && scope?.parentElement; i++) {
        scope = scope.parentElement;
      }
      const container = scope || document.body;

      const candidates = Array.from(
        container.querySelectorAll('button, div[role="button"], [role="button"]')
      ) as HTMLElement[];

      const withSvg = candidates.filter((el) => {
        if (el.closest('#mcp-popover-container')) return false;
        if (this.isStopButton(el)) return false;
        const rect = el.getBoundingClientRect();
        return !!el.querySelector('svg') && rect.width > 0 && rect.height > 0;
      });

      if (withSvg.length > 0) {
        withSvg.sort((a, b) => b.getBoundingClientRect().right - a.getBoundingClientRect().right);
        this.context.logger.debug('Found submit button via heuristic (svg button near input)');
        return withSvg[0];
      }
    }

    return null;
  }

  /**
   * Heuristically decide whether a button is currently the "Stop generating"
   * control rather than the "Send" control. On Xiaomi the same button toggles
   * between Send (arrow) and Stop (square) while a response is streaming.
   * Auto-submit must never click this, or it aborts the generation.
   */
  private isStopButton(el: HTMLElement | null): boolean {
    if (!el) return false;
    const parts = [
      el.getAttribute('aria-label') || '',
      el.getAttribute('title') || '',
      el.getAttribute('data-testid') || '',
      el.className || '',
      el.textContent || ''
    ];
    const haystack = parts.join(' ').toLowerCase();
    const stopWords = ['stop', '\u0441\u0442\u043e\u043f', '\u043e\u0441\u0442\u0430\u043d\u043e\u0432', '\u043f\u0440\u0435\u043a\u0440\u0430\u0442', '\u505c\u6b62', 'halt', 'abort'];
    if (stopWords.some(w => haystack.includes(w))) return true;

    // Square/rect "stop" glyph: an svg whose icon is a <rect> (the stop square)
    // with no arrow path/polygon.
    const svg = el.querySelector('svg');
    if (svg) {
      const hasRect = !!svg.querySelector('rect');
      const hasArrow = !!svg.querySelector('path, polygon, line');
      if (hasRect && !hasArrow) return true;
    }
    return false;
  }

  /**
   * Find the "Stop generating" button if one is currently shown (i.e. the model
   * is streaming a response). Used to avoid clicking it during auto-submit.
   */
  private findStopButton(): HTMLElement | null {
    const input = this.findChatInputElement();
    let scope: HTMLElement | null = input;
    for (let i = 0; i < 5 && scope?.parentElement; i++) {
      scope = scope.parentElement;
    }
    const container = scope || document.body;
    const candidates = Array.from(
      container.querySelectorAll('button, div[role="button"], [role="button"]')
    ) as HTMLElement[];
    for (const el of candidates) {
      if (el.closest('#mcp-popover-container')) continue;
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) continue;
      if (this.isStopButton(el)) return el;
    }
    return null;
  }

  private async tryEnterKeySubmission(): Promise<boolean> {
    try {
      // If generation is already running (Stop button visible), the message was
      // already sent; pressing Enter now is useless and could interrupt it.
      if (this.findStopButton()) {
        this.context.logger.debug('Stop button present; skipping Enter-key fallback to avoid interrupting generation');
        this.emitExecutionCompleted('submitForm', {}, {
          success: true,
          method: 'already-generating',
          fallback: true
        });
        return true;
      }

      const chatInput = this.findChatInputElement();
      if (!chatInput) {
        this.context.logger.error('Cannot find chat input for Enter key submission');
        this.emitExecutionFailed('submitForm', 'Chat input not found for Enter key submission');
        return false;
      }

      chatInput.focus();

      const eventTypes: Array<'keydown' | 'keypress' | 'keyup'> = ['keydown', 'keypress', 'keyup'];
      for (const type of eventTypes) {
        chatInput.dispatchEvent(new KeyboardEvent(type, {
          key: 'Enter',
          code: 'Enter',
          keyCode: 13,
          which: 13,
          bubbles: true,
          cancelable: true,
        }));
      }

      const form = chatInput.closest('form');
      if (form) {
        form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
      }

      this.emitExecutionCompleted('submitForm', {}, {
        success: true,
        method: 'enterKey',
        fallback: true
      });
      this.context.logger.debug('Xiaomi chat input submitted using Enter key');
      return true;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      this.context.logger.error(`Error submitting Xiaomi chat input via Enter key: ${errorMessage}`);
      this.emitExecutionFailed('submitForm', errorMessage);
      return false;
    }
  }

  isSupported(): boolean | Promise<boolean> {
    const currentHost = window.location.hostname;
    const isHost = this.hostnames.some(hostname =>
      typeof hostname === 'string' ? currentHost.includes(hostname) : (hostname as RegExp).test(currentHost)
    );
    if (!isHost) {
      this.context.logger.debug(`Host ${currentHost} not supported by Xiaomi adapter`);
      return false;
    }
    return true;
  }

  // ---- URL tracking ----
  private setupUrlTracking(): void {
    if (!this.urlCheckInterval) {
      this.urlCheckInterval = setInterval(() => {
        const currentUrl = window.location.href;
        if (currentUrl !== this.lastUrl) {
          this.context.logger.debug(`URL changed from ${this.lastUrl} to ${currentUrl}`);
          if (this.onPageChanged) {
            this.onPageChanged(currentUrl, this.lastUrl);
          }
          this.lastUrl = currentUrl;
        }
      }, 1000);
    }
  }

  // ---- store / DOM / UI integration ----
  private setupStoreEventListeners(): void {
    if (this.storeEventListenersSetup) return;
    this.context.logger.debug(`Setting up store event listeners for Xiaomi adapter instance #${this.instanceId}`);
    this.context.eventBus.on('tool:execution-completed', (data) => {
      this.context.logger.debug('Tool execution completed:', data);
    });
    this.storeEventListenersSetup = true;
  }

  private setupDOMObservers(): void {
    if (this.domObserversSetup) return;
    this.context.logger.debug(`Setting up DOM observers for Xiaomi adapter instance #${this.instanceId}`);
    this.mutationObserver = new MutationObserver((mutations) => {
      let shouldReinject = false;
      mutations.forEach((mutation) => {
        if (mutation.type === 'childList') {
          if (!document.getElementById('mcp-popover-container')) {
            shouldReinject = true;
          }
        }
      });
      if (shouldReinject) {
        const insertionPoint = this.findButtonInsertionPoint();
        if (insertionPoint) {
          this.context.logger.debug('MCP popover removed, attempting to re-inject');
          this.setupUIIntegration();
        }
      }
    });
    this.mutationObserver.observe(document.body, { childList: true, subtree: true });
    this.domObserversSetup = true;
  }

  private setupUIIntegration(): void {
    if (this.uiIntegrationSetup) {
      this.context.logger.debug(`UI integration already set up for instance #${this.instanceId}, re-injecting`);
    } else {
      this.context.logger.debug(`Setting up UI integration for Xiaomi adapter instance #${this.instanceId}`);
      this.uiIntegrationSetup = true;
    }
    this.waitForPageReady().then(() => {
      this.injectMCPPopoverWithRetry();
    }).catch((error) => {
      this.context.logger.warn('Failed to wait for page ready:', error);
    });
  }

  private async waitForPageReady(): Promise<void> {
    return new Promise((resolve, reject) => {
      let attempts = 0;
      const maxAttempts = 10;
      const checkReady = () => {
        attempts++;
        const insertionPoint = this.findButtonInsertionPoint();
        if (insertionPoint) {
          this.context.logger.debug('Page ready for MCP popover injection');
          resolve();
        } else if (attempts >= maxAttempts) {
          this.context.logger.warn('Page ready check timed out - no insertion point found');
          reject(new Error('No insertion point found after maximum attempts'));
        } else {
          setTimeout(checkReady, 500);
        }
      };
      setTimeout(checkReady, 100);
    });
  }

  private injectMCPPopoverWithRetry(maxRetries: number = 5): void {
    const attemptInjection = (attempt: number) => {
      this.context.logger.debug(`Attempting MCP popover injection (attempt ${attempt}/${maxRetries})`);
      if (document.getElementById('mcp-popover-container')) {
        this.context.logger.debug('MCP popover already exists');
        return;
      }
      const insertionPoint = this.findButtonInsertionPoint();
      if (insertionPoint) {
        this.injectMCPPopover(insertionPoint);
      } else if (attempt < maxRetries) {
        setTimeout(() => attemptInjection(attempt + 1), 1000);
      } else {
        this.context.logger.warn('Failed to inject MCP popover after maximum retries');
      }
    };
    attemptInjection(1);
  }

  private cleanupDOMObservers(): void {
    if (this.mutationObserver) {
      this.mutationObserver.disconnect();
      this.mutationObserver = null;
    }
  }

  private cleanupUIIntegration(): void {
    const popoverContainer = document.getElementById('mcp-popover-container');
    if (popoverContainer) {
      popoverContainer.remove();
    }
    this.mcpPopoverContainer = null;
  }

  /**
   * Find where to inject the MCP popover button. Xiaomi's action row has no
   * stable class names, so we anchor to the send button (or the input) and
   * insert the popover next to it.
   */
  private findButtonInsertionPoint(): { container: Element; insertAfter: Element | null } | null {
    const sendButton = this.findSubmitButton();
    if (sendButton && sendButton.parentElement) {
      this.context.logger.debug('Using send button row as insertion point');
      return { container: sendButton.parentElement, insertAfter: sendButton };
    }

    const input = this.findChatInputElement();
    if (input) {
      let scope: HTMLElement | null = input;
      for (let i = 0; i < 5 && scope?.parentElement; i++) {
        scope = scope.parentElement;
        const btn = scope.querySelector('button, [role="button"]');
        if (btn && !btn.closest('#mcp-popover-container')) {
          this.context.logger.debug('Using ancestor container with a button as insertion point');
          return { container: scope, insertAfter: scope.lastElementChild };
        }
      }
      if (input.parentElement) {
        this.context.logger.debug('Using input parent as insertion point (fallback)');
        return { container: input.parentElement, insertAfter: input };
      }
    }

    this.context.logger.debug('Could not find suitable insertion point for MCP popover');
    return null;
  }

  private injectMCPPopover(insertionPoint: { container: Element; insertAfter: Element | null }): void {
    this.context.logger.debug('Injecting MCP popover into Xiaomi interface');
    try {
      if (document.getElementById('mcp-popover-container')) {
        this.context.logger.debug('MCP popover already exists, skipping injection');
        return;
      }
      const reactContainer = document.createElement('div');
      reactContainer.id = 'mcp-popover-container';
      reactContainer.style.display = 'inline-block';
      reactContainer.style.margin = '0 4px';

      const { container, insertAfter } = insertionPoint;
      if (insertAfter && insertAfter.parentNode === container) {
        container.insertBefore(reactContainer, insertAfter.nextSibling);
      } else {
        container.appendChild(reactContainer);
      }

      this.mcpPopoverContainer = reactContainer;
      this.renderMCPPopover(reactContainer);
      this.context.logger.debug('MCP popover injected and rendered successfully');
    } catch (error) {
      this.context.logger.error('Failed to inject MCP popover:', error);
    }
  }

  private renderMCPPopover(container: HTMLElement): void {
    this.context.logger.debug('Rendering MCP popover');
    try {
      import('react').then(React => {
        import('react-dom/client').then(ReactDOM => {
          import('../../components/mcpPopover/mcpPopover').then(({ MCPPopover }) => {
            const toggleStateManager = this.createToggleStateManager();
            const root = ReactDOM.createRoot(container);
            root.render(
              React.createElement(MCPPopover, {
                toggleStateManager: toggleStateManager
              })
            );
            this.context.logger.debug('MCP popover rendered successfully');
          }).catch(error => {
            this.context.logger.error('Failed to import MCPPopover component:', error);
          });
        }).catch(error => {
          this.context.logger.error('Failed to import ReactDOM:', error);
        });
      }).catch(error => {
        this.context.logger.error('Failed to import React:', error);
      });
    } catch (error) {
      this.context.logger.error('Failed to render MCP popover:', error);
    }
  }

  private createToggleStateManager() {
    const context = this.context;
    const stateManager = {
      getState: () => {
        try {
          const uiState = context.stores.ui;
          const mcpEnabled = uiState?.mcpEnabled ?? false;
          const autoSubmitEnabled = uiState?.preferences?.autoSubmit ?? false;
          return {
            mcpEnabled: mcpEnabled,
            autoInsert: autoSubmitEnabled,
            autoSubmit: autoSubmitEnabled,
            autoExecute: false
          };
        } catch (error) {
          context.logger.error('Error getting toggle state:', error);
          return { mcpEnabled: false, autoInsert: false, autoSubmit: false, autoExecute: false };
        }
      },

      setMCPEnabled: (enabled: boolean) => {
        context.logger.debug(`Setting MCP ${enabled ? 'enabled' : 'disabled'}`);
        try {
          if (context.stores.ui?.setMCPEnabled) {
            context.stores.ui.setMCPEnabled(enabled, 'mcp-popover-toggle');
          } else if (context.stores.ui?.setSidebarVisibility) {
            context.stores.ui.setSidebarVisibility(enabled, 'mcp-popover-toggle-fallback');
          }
          const sidebarManager = (window as any).activeSidebarManager;
          if (sidebarManager) {
            if (enabled) {
              sidebarManager.show().catch((error: any) => context.logger.error('Error showing sidebar:', error));
            } else {
              sidebarManager.hide().catch((error: any) => context.logger.error('Error hiding sidebar:', error));
            }
          }
        } catch (error) {
          context.logger.error('Error in setMCPEnabled:', error);
        }
        stateManager.updateUI();
      },

      setAutoInsert: (enabled: boolean) => {
        if (context.stores.ui?.updatePreferences) {
          context.stores.ui.updatePreferences({ autoSubmit: enabled });
        }
        stateManager.updateUI();
      },

      setAutoSubmit: (enabled: boolean) => {
        if (context.stores.ui?.updatePreferences) {
          context.stores.ui.updatePreferences({ autoSubmit: enabled });
        }
        stateManager.updateUI();
      },

      setAutoExecute: (enabled: boolean) => {
        stateManager.updateUI();
      },

      updateUI: () => {
        const popoverContainer = document.getElementById('mcp-popover-container');
        if (popoverContainer) {
          const currentState = stateManager.getState();
          const event = new CustomEvent('mcp:update-toggle-state', {
            detail: { toggleState: currentState }
          });
          popoverContainer.dispatchEvent(event);
        }
      }
    };
    return stateManager;
  }

  public injectMCPPopoverManually(): void {
    this.injectMCPPopoverWithRetry();
  }

  public isMCPPopoverInjected(): boolean {
    return !!document.getElementById('mcp-popover-container');
  }

  private emitExecutionCompleted(toolName: string, parameters: any, result: any): void {
    this.context.eventBus.emit('tool:execution-completed', {
      execution: {
        id: this.generateCallId(),
        toolName,
        parameters,
        result,
        timestamp: Date.now(),
        status: 'success'
      }
    });
  }

  private emitExecutionFailed(toolName: string, error: string): void {
    this.context.eventBus.emit('tool:execution-failed', {
      toolName,
      error,
      callId: this.generateCallId()
    });
  }

  private generateCallId(): string {
    return `xiaomimimo-${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
  }

  onPageChanged?(url: string, oldUrl?: string): void {
    this.context.logger.debug(`Xiaomi page changed: from ${oldUrl || 'N/A'} to ${url}`);
    this.lastUrl = url;
    const stillSupported = this.isSupported();
    if (stillSupported) {
      setTimeout(() => {
        this.setupUIIntegration();
      }, 1000);
    }
    this.context.eventBus.emit('app:site-changed', {
      site: url,
      hostname: window.location.hostname
    });
  }

  onHostChanged?(newHost: string, oldHost?: string): void {
    this.context.logger.debug(`Xiaomi host changed: from ${oldHost || 'N/A'} to ${newHost}`);
    const stillSupported = this.isSupported();
    if (!stillSupported) {
      this.context.eventBus.emit('adapter:deactivated', {
        pluginName: this.name,
        timestamp: Date.now()
      });
    } else {
      this.setupUIIntegration();
    }
  }

  onToolDetected?(tools: any[]): void {
    this.context.logger.debug('Tools detected in Xiaomi adapter:', tools);
    tools.forEach(tool => {
      this.context.stores.tool?.addDetectedTool?.(tool);
    });
  }
}
