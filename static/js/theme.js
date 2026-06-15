/**
 * RegisGuard — Theme System runtime
 *
 * 职责：统一管理 Admin_Panel 的主题状态机，包含纯函数（`resolveTheme` /
 * `normalizeMode`）与副作用入口（`load` / `apply` / `init`）。
 *
 * 任务 4.1：定义两个纯函数 `resolveTheme`、`normalizeMode`。
 * 任务 4.4：追加 `load`、`apply`、`init` 三个方法，串起 localStorage、
 *           matchMedia 与 Theme_Switcher 的状态同步；切换主题时仅更新
 *           `<html>.dataset.theme` 与 `.theme-btn[aria-pressed]`，不触碰
 *           任何 `<link rel="stylesheet">` / `<style>` 元素。
 *
 * 设计文档：.kiro/specs/responsive-theme-system/design.md
 *   §Components and Interfaces → 2. theme.js
 * 关联需求：2.3, 2.4, 2.5, 2.6, 2.8, 2.9, 3.3, 3.4, 3.5, 3.6, 3.7,
 *           4.1, 4.2, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 5.5,
 *           14.2, 14.3, 14.4
 */
(function () {
    'use strict';

    /** localStorage 中持久化 Theme_Mode 的键名（Theme_Storage_Key）。 */
    var STORAGE_KEY = 'regisguard-theme';

    /** Theme_Switcher 中按钮的 CSS 选择器。 */
    var SWITCHER_BTN_SELECTOR = '.theme-btn';

    /** 单例标记：`init()` 只允许真正执行一次（含事件订阅与点击绑定）。 */
    var initialized = false;

    /**
     * 校验并归一化 Theme_Mode 字面量。
     *
     * 仅接受字符串字面量 `"light"`、`"dark"`、`"system"` 三者之一，
     * 使用严格相等（`===`）比较，不做任何类型强制转换。
     * 任何其他输入（数字、布尔、`null`、`undefined`、对象、其他字符串等）一律返回 `null`。
     *
     * @param {unknown} value 待校验的任意值
     * @returns {"light"|"dark"|"system"|null} 命中枚举时返回原字面量，否则 `null`
     */
    function normalizeMode(value) {
        if (value === 'light' || value === 'dark' || value === 'system') {
            return value;
        }
        return null;
    }

    /**
     * 将 Theme_Mode 与 System_Theme_Preference 解析为最终的 `data-theme` 取值。
     *
     * 真值表（见 design.md §Components and Interfaces → 2. theme.js）：
     *   mode === "dark"                                    → "dark"
     *   mode === "light"                                   → "light"
     *   mode === "system" && systemPref === "dark"         → "dark"
     *   mode === "system" && systemPref !== "dark"         → "light"
     *   其他（含非法 mode、非法 systemPref）                → "light"
     *
     * 该函数为纯函数：相同入参始终返回相同结果，无副作用。
     *
     * @param {"light"|"dark"|"system"|string} mode 用户选择的 Theme_Mode
     * @param {"light"|"dark"|string} systemPref 浏览器探测到的系统主题偏好
     * @returns {"light"|"dark"} 实际应写入 `<html>.data-theme` 的值
     */
    function resolveTheme(mode, systemPref) {
        if (mode === 'dark') {
            return 'dark';
        }
        if (mode === 'light') {
            return 'light';
        }
        if (mode === 'system' && systemPref === 'dark') {
            return 'dark';
        }
        return 'light';
    }

    /**
     * 读取浏览器当前的 System_Theme_Preference。
     *
     * 任意异常（matchMedia 不可用、抛错、`matches` 取值异常）一律降级为 `"light"`，
     * 这与 R4.7 的"`prefers-color-scheme` 不可探测时默认应用 Light_Theme"保持一致。
     *
     * @returns {"light"|"dark"} 当前系统偏好；不可探测时返回 `"light"`
     */
    function getSystemPref() {
        try {
            if (typeof window.matchMedia !== 'function') {
                return 'light';
            }
            var mql = window.matchMedia('(prefers-color-scheme: dark)');
            if (mql && mql.matches === true) {
                return 'dark';
            }
        } catch (e) {
            /* matchMedia 抛异常 → 视同不可探测，回退 light */
        }
        return 'light';
    }

    /**
     * 将 Theme_Switcher 中各按钮的 `aria-pressed` 状态同步为：
     *   仅 `data-theme-mode === activeMode` 的按钮为 `"true"`，其余为 `"false"`。
     *
     * 不修改其它属性（包括 `disabled`、`hidden` 等），不插入 / 删除按钮节点；
     * 不触碰任何 `<link rel="stylesheet">` / `<style>` 元素。
     *
     * @param {"light"|"dark"|"system"} activeMode 当前生效的 Theme_Mode
     */
    function syncSwitcherState(activeMode) {
        if (typeof document === 'undefined' || !document.querySelectorAll) {
            return;
        }
        var buttons = document.querySelectorAll(SWITCHER_BTN_SELECTOR);
        for (var i = 0; i < buttons.length; i++) {
            var btn = buttons[i];
            var pressed = btn.dataset && btn.dataset.themeMode === activeMode;
            btn.setAttribute('aria-pressed', pressed ? 'true' : 'false');
        }
    }

    /**
     * 安全地将 `<html>` 元素的 `data-theme` 设为指定值。
     *
     * 仅写入属性，不读取、移除、重新插入任何 `<link>` / `<style>` 节点
     * （满足 R14.3 / R14.4 / Property 22）。
     *
     * @param {"light"|"dark"} value 期望的 `data-theme` 取值
     */
    function writeDataTheme(value) {
        if (typeof document === 'undefined' || !document.documentElement) {
            return;
        }
        document.documentElement.setAttribute('data-theme', value);
    }

    /**
     * 从 `localStorage` 读取已持久化的 Theme_Mode。
     *
     * - `localStorage.getItem` 抛异常（隐私模式 / 存储被禁用）→ 返回 `"system"`。
     * - 取值缺失（`null`、空字符串）或不在 `{light, dark, system}` 集合内 → 返回 `"system"`。
     * - 命中合法值 → 直接返回该字面量。
     *
     * 该函数对外保证：在任何环境下都不会向调用方抛出异常。
     *
     * @returns {"light"|"dark"|"system"} 当前 Theme_Mode；异常 / 缺失 / 非法时为 `"system"`
     */
    function load() {
        try {
            var stored = window.localStorage.getItem(STORAGE_KEY);
            var normalized = normalizeMode(stored);
            if (normalized !== null) {
                return normalized;
            }
        } catch (e) {
            /* localStorage 不可用 → 回退 system */
        }
        return 'system';
    }

    /**
     * 将传入的 `mode` 应用到运行时状态：
     *   1. 归一化 → 非法时把 `<html>.data-theme` 写为 `"light"`，**不**写 localStorage、
     *      **不**变更 Switcher，并返回 `{ ok: false, error: "invalid_mode", applied: "light", mode }`。
     *   2. 合法时调用 `resolveTheme(mode, systemPref)` 计算实际 `data-theme`，
     *      写入 `<html>.dataset.theme`，以 `try/catch` 持久化到 `localStorage`，
     *      并将 Switcher 的 `aria-pressed` 状态同步到 `mode`。
     *
     * 切换过程中仅修改 `<html>.dataset.theme` 与 `.theme-btn[aria-pressed]`，
     * 不会移除 / 重新插入 / 修改任何 `<link rel="stylesheet">` 或 `<style>` 元素，
     * 满足 R14.2 / R14.3 / R14.4。
     *
     * @param {unknown} mode 期望应用的 Theme_Mode（字符串字面量或任意非法值）
     * @returns {{ ok: true, applied: "light"|"dark", mode: "light"|"dark"|"system" } |
     *          { ok: false, error: "invalid_mode", applied: "light", mode: unknown }}
     */
    function apply(mode) {
        var normalized = normalizeMode(mode);
        if (normalized === null) {
            // 非法 mode：将 <html>.data-theme 强制回退到 "light"，
            // 不持久化、不更新 Switcher 状态，以免淹没用户的实际选择。
            writeDataTheme('light');
            return {
                ok: false,
                error: 'invalid_mode',
                applied: 'light',
                mode: mode,
            };
        }
        var systemPref = getSystemPref();
        var resolved = resolveTheme(normalized, systemPref);
        writeDataTheme(resolved);
        try {
            window.localStorage.setItem(STORAGE_KEY, normalized);
        } catch (e) {
            /* 存储不可用 → 静默忽略，本次切换仅在内存生效 */
        }
        syncSwitcherState(normalized);
        return {
            ok: true,
            applied: resolved,
            mode: normalized,
        };
    }

    /**
     * 处理 Theme_Switcher 按钮点击事件：将其 `data-theme-mode` 交给 `apply()`。
     */
    function handleSwitcherClick(event) {
        var target = event && event.currentTarget;
        if (!target || !target.dataset) {
            return;
        }
        apply(target.dataset.themeMode);
    }

    /**
     * `prefers-color-scheme` `change` 事件处理器。
     *
     * - 仅在当前 Theme_Mode 为 `"system"` 时更新 `<html>.data-theme`；
     *   否则短路返回（订阅本身保持，Property 5 要求"监听器数量恒 ≤ 1"）。
     * - 不修改 `localStorage`，不调整 Switcher 状态（mode 未变化）。
     *
     * @param {MediaQueryListEvent} event
     */
    function handleSystemPrefChange(event) {
        var currentMode = load();
        if (currentMode !== 'system') {
            return;
        }
        var pref = event && event.matches === true ? 'dark' : 'light';
        writeDataTheme(resolveTheme('system', pref));
    }

    /**
     * 单次注册 `prefers-color-scheme` 变更订阅。
     *
     * - matchMedia 不可用、返回伪 `MediaQueryList`、或 `addEventListener` 抛异常时：
     *   停止后续订阅尝试，并把 `<html>.data-theme` 强制设为 `"light"`（R5.5）。
     * - 成功订阅后，监听器内部根据 `load()` 当前值决定是否真正更新 DOM；
     *   订阅本身始终保持以确保 Property 5 的"监听器数量 ≤ 1"。
     *
     * @returns {boolean} `true` 表示订阅成功；`false` 表示已降级为静态 light
     */
    function subscribeSystemPref() {
        try {
            if (typeof window.matchMedia !== 'function') {
                throw new Error('matchMedia unavailable');
            }
            var mql = window.matchMedia('(prefers-color-scheme: dark)');
            if (!mql || typeof mql.addEventListener !== 'function') {
                throw new Error('mediaQueryList.addEventListener unavailable');
            }
            mql.addEventListener('change', handleSystemPrefChange);
            return true;
        } catch (e) {
            // 任何环境异常 → 直接降级到 Light_Theme，停止后续订阅尝试
            writeDataTheme('light');
            return false;
        }
    }

    /**
     * 绑定 Theme_Switcher 按钮的 `click` 事件。多次调用安全：
     * 由 `init()` 通过 `initialized` 单例标记保证仅注册一次。
     */
    function bindSwitcherClicks() {
        if (typeof document === 'undefined' || !document.querySelectorAll) {
            return;
        }
        var buttons = document.querySelectorAll(SWITCHER_BTN_SELECTOR);
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].addEventListener('click', handleSwitcherClick);
        }
    }

    /**
     * 初始化 Theme_System 运行时：
     *   - 单次注册 `prefers-color-scheme` 的 `change` 监听器；
     *     不可用时把 `<html>.data-theme` 设为 `"light"`，停止后续订阅尝试。
     *   - 绑定 `.theme-btn` 的 `click` → `apply(button.dataset.themeMode)`。
     *   - 同步 Switcher 选中态以匹配 `load()` 返回的当前 Theme_Mode；
     *     `<html>.data-theme` 在首屏阶段已由 `<head>` 的 FOUC 内联脚本写入。
     *
     * 多次调用安全：仅在首次调用时真正执行副作用，后续调用直接返回。
     */
    function init() {
        if (initialized) {
            return;
        }
        initialized = true;

        // 1. 系统偏好订阅（始终保持，监听器内部按 mode 决定是否更新 DOM）
        subscribeSystemPref();

        // 2. 绑定 Switcher 点击事件（一次性）
        bindSwitcherClicks();

        // 3. 同步 Switcher 选中态到当前持久化 mode（FOUC 脚本已设置 data-theme）
        syncSwitcherState(load());
    }

    window.RGTheme = {
        resolveTheme: resolveTheme,
        normalizeMode: normalizeMode,
        load: load,
        apply: apply,
        init: init,
    };
})();
