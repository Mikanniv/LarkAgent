import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

class LarkOrbitShortcut {
  const LarkOrbitShortcut({
    required this.id,
    required this.label,
    required this.icon,
    required this.onTap,
    this.badgeCount = 0,
  });

  final String id;
  final String label;
  final IconData icon;
  final VoidCallback onTap;
  final int badgeCount;
}

class LarkGreetings {
  static const Map<String, List<String>> _bySlot = {
    'morning': [
      '早上好，准备开始一天的学习了吗？',
      '早安呀，新的一天我们慢慢来，先定一个小目标吧。',
      '早上好！精神不错的话，要不要先去自习室热热身？',
    ],
    'noon': [
      '中午好，记得好好吃午饭、休息一会儿再继续哦。',
      '午间时间到啦，劳逸结合效率才会更高。',
      '中午好呀，上午的进度怎么样？可以和我聊聊。',
    ],
    'afternoon': [
      '下午好，要一起推进今天的学习任务吗？',
      '午后容易犯困，喝口水，我陪你把重点过一遍吧。',
      '下午好呀，有想问的问题或者想聊的心事随时找我。',
    ],
    'evening': [
      '晚上好，今天辛苦啦，要不要一起复盘一下今天的收获？',
      '晚上好呀，写篇日记或者轻松聊聊天都很不错。',
      '傍晚安静下来了，今晚打算复习哪一块呢？',
    ],
    'night': [
      '晚上了，该休息啦，别熬夜太久哦。',
      '夜深了，今天就先到这里吧，明天我还在。',
      '已经很晚啦，早点睡个好觉，晚安。',
    ],
  };

  static String slotForHour(int hour) {
    if (hour >= 5 && hour < 11) return 'morning';
    if (hour >= 11 && hour < 14) return 'noon';
    if (hour >= 14 && hour < 18) return 'afternoon';
    if (hour >= 18 && hour < 22) return 'evening';
    return 'night';
  }

  static List<String> listForNow([DateTime? now]) {
    final dt = now ?? DateTime.now();
    return _bySlot[slotForHour(dt.hour)] ?? _bySlot['morning']!;
  }
}

class LarkHomeStage extends StatefulWidget {
  const LarkHomeStage({
    super.key,
    required this.apiBase,
    required this.shortcuts,
    required this.backendOnline,
    this.active = true,
  });

  final String apiBase;
  final List<LarkOrbitShortcut> shortcuts;
  final bool backendOnline;
  final bool active;

  @override
  State<LarkHomeStage> createState() => _LarkHomeStageState();
}

class _LarkHomeStageState extends State<LarkHomeStage>
    with SingleTickerProviderStateMixin {
  late final AnimationController _floatCtrl;
  WebViewController? _webCtrl;
  bool _live2dReady = false;
  bool _live2dFailed = false;
  int _greetingIdx = 0;
  String _greetingSlot = '';

  bool get _supportsLive2dWebView =>
      !kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.android ||
          defaultTargetPlatform == TargetPlatform.iOS);

  @override
  void initState() {
    super.initState();
    _greetingSlot = LarkGreetings.slotForHour(DateTime.now().hour);
    _floatCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 3600),
    );
    if (widget.active) {
      _floatCtrl.repeat(reverse: true);
      if (_supportsLive2dWebView) {
        _initLive2dWebView();
      }
    }
  }

  @override
  void didUpdateWidget(covariant LarkHomeStage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active != oldWidget.active) {
      if (widget.active) {
        _floatCtrl.repeat(reverse: true);
        if (_supportsLive2dWebView && _webCtrl == null && !_live2dFailed) {
          _initLive2dWebView();
        }
      } else {
        _floatCtrl.stop();
      }
    }
  }

  void _initLive2dWebView() {
    if (WebViewPlatform.instance == null) {
      _live2dFailed = true;
      return;
    }
    final base = widget.apiBase.trim().replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.tryParse('$base/live2d-embed.html');
    if (uri == null) return;
    try {
      final ctrl = WebViewController()
        ..setJavaScriptMode(JavaScriptMode.unrestricted)
        ..setBackgroundColor(const Color(0x00000000))
        ..setNavigationDelegate(
          NavigationDelegate(
            onPageFinished: (_) {
              if (mounted) {
                setState(() {
                  _live2dReady = true;
                });
              }
            },
            onWebResourceError: (_) {
              if (mounted) {
                setState(() {
                  _live2dFailed = true;
                });
              }
            },
          ),
        )
        ..loadRequest(uri);
      _webCtrl = ctrl;
    } catch (_) {
      _live2dFailed = true;
    }
  }

  @override
  void dispose() {
    _floatCtrl.dispose();
    super.dispose();
  }

  String _currentGreeting() {
    final slot = LarkGreetings.slotForHour(DateTime.now().hour);
    if (slot != _greetingSlot) {
      _greetingSlot = slot;
      _greetingIdx = 0;
    }
    final list = LarkGreetings.listForNow();
    return list[_greetingIdx % list.length];
  }

  void _nextGreeting() {
    final list = LarkGreetings.listForNow();
    setState(() {
      _greetingIdx = (_greetingIdx + 1) % list.length;
    });
  }

  @override
  Widget build(BuildContext context) {
    final greeting = _currentGreeting();
    return Container(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [
            Color(0xFFF6FAFF),
            Color(0xFFEEF5FD),
            Color(0xFFF9FBFF),
          ],
        ),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final w = constraints.maxWidth;
          final h = constraints.maxHeight;
          final stageSize = math.min(w * 0.62, h * 0.44).clamp(190.0, 290.0);
          final leftItems = <LarkOrbitShortcut>[];
          final rightItems = <LarkOrbitShortcut>[];
          LarkOrbitShortcut? bottomItem;
          for (var i = 0; i < widget.shortcuts.length; i++) {
            final item = widget.shortcuts[i];
            if (i == widget.shortcuts.length - 1 &&
                widget.shortcuts.length.isOdd) {
              bottomItem = item;
            } else if (i.isEven) {
              leftItems.add(item);
            } else {
              rightItems.add(item);
            }
          }

          return Stack(
            children: [
              // Subtle ambient glow behind Lark
              Align(
                alignment: const Alignment(0, 0.08),
                child: Container(
                  width: stageSize * 1.05,
                  height: stageSize * 1.05,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: RadialGradient(
                      colors: [
                        const Color(0xFF8CC4F8).withValues(alpha: 0.24),
                        const Color(0xFF8CC4F8).withValues(alpha: 0.0),
                      ],
                    ),
                  ),
                ),
              ),

              // Center Live2D / Seated Lark Character
              Align(
                alignment: const Alignment(0, 0.08),
                child: GestureDetector(
                  onTap: _nextGreeting,
                  child: SizedBox(
                    width: stageSize,
                    height: stageSize * 1.18,
                    child: Stack(
                      alignment: Alignment.center,
                      children: [
                        AnimatedBuilder(
                          animation: _floatCtrl,
                          builder: (context, child) {
                            final dy =
                                math.sin(_floatCtrl.value * math.pi) * 5.0;
                            return Transform.translate(
                              offset: Offset(0, -dy),
                              child: child,
                            );
                          },
                          child: AnimatedOpacity(
                            duration: const Duration(milliseconds: 280),
                            opacity: (_live2dReady && !_live2dFailed) ? 0.0 : 1.0,
                            child: Image.asset(
                              'assets/human-seated.png',
                              fit: BoxFit.contain,
                            ),
                          ),
                        ),
                        if (_webCtrl != null && !_live2dFailed)
                          IgnorePointer(
                            ignoring: false,
                            child: AnimatedOpacity(
                              duration: const Duration(milliseconds: 320),
                              opacity: _live2dReady ? 1.0 : 0.0,
                              child: WebViewWidget(controller: _webCtrl!),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              ),

              // Time-based Greeting Speech Bubble above Lark
              Positioned(
                top: 14,
                left: 16,
                right: 16,
                child: Center(
                  child: _GreetingSpeechBubble(
                    text: greeting,
                    onTap: _nextGreeting,
                  ),
                ),
              ),

              // Orbiting Shortcut Bubbles (Left Arc)
              Positioned(
                left: 12,
                top: math.max(92, h * 0.16),
                bottom: math.max(88, h * 0.15),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (var i = 0; i < leftItems.length; i++)
                      _OrbitBubbleButton(
                        shortcut: leftItems[i],
                        animation: _floatCtrl,
                        phase: i * 1.1,
                        indent: i == 1 ? 0 : 12,
                      ),
                  ],
                ),
              ),

              // Orbiting Shortcut Bubbles (Right Arc)
              Positioned(
                right: 12,
                top: math.max(92, h * 0.16),
                bottom: math.max(88, h * 0.15),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    for (var i = 0; i < rightItems.length; i++)
                      _OrbitBubbleButton(
                        shortcut: rightItems[i],
                        animation: _floatCtrl,
                        phase: (i + 0.5) * 1.2,
                        indent: i == 1 ? 0 : 12,
                        alignRight: true,
                      ),
                  ],
                ),
              ),

              // Bottom Center Bubble (if odd number of shortcuts)
              if (bottomItem != null)
                Positioned(
                  left: 0,
                  right: 0,
                  bottom: 22,
                  child: Center(
                    child: _OrbitBubbleButton(
                      shortcut: bottomItem,
                      animation: _floatCtrl,
                      phase: 2.2,
                    ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}

class _GreetingSpeechBubble extends StatelessWidget {
  const _GreetingSpeechBubble({required this.text, required this.onTap});

  final String text;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            constraints: const BoxConstraints(maxWidth: 330),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.94),
              borderRadius: BorderRadius.circular(999),
              border: Border.all(
                color: const Color(0xFF7AA5CE).withValues(alpha: 0.36),
              ),
              boxShadow: [
                BoxShadow(
                  color: const Color(0xFF305680).withValues(alpha: 0.10),
                  blurRadius: 18,
                  offset: const Offset(0, 6),
                ),
              ],
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 8,
                  height: 8,
                  decoration: const BoxDecoration(
                    color: Color(0xFF6DAAE6),
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 8),
                Flexible(
                  child: Text(
                    text,
                    style: const TextStyle(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w500,
                      color: Color(0xFF354C66),
                      height: 1.35,
                    ),
                  ),
                ),
              ],
            ),
          ),
          CustomPaint(
            size: const Size(14, 7),
            painter: _BubbleTailPainter(),
          ),
        ],
      ),
    );
  }
}

class _BubbleTailPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()
      ..moveTo(0, 0)
      ..lineTo(size.width / 2, size.height)
      ..lineTo(size.width, 0)
      ..close();
    canvas.drawPath(
      path,
      Paint()..color = Colors.white.withValues(alpha: 0.94),
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class _OrbitBubbleButton extends StatelessWidget {
  const _OrbitBubbleButton({
    required this.shortcut,
    required this.animation,
    required this.phase,
    this.indent = 0,
    this.alignRight = false,
  });

  final LarkOrbitShortcut shortcut;
  final Animation<double> animation;
  final double phase;
  final double indent;
  final bool alignRight;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: animation,
      builder: (context, child) {
        final dy = math.sin(animation.value * math.pi * 2 + phase) * 3.5;
        return Transform.translate(
          offset: Offset(alignRight ? -indent : indent, dy),
          child: child,
        );
      },
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: shortcut.onTap,
          borderRadius: BorderRadius.circular(22),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.92),
              borderRadius: BorderRadius.circular(22),
              border: Border.all(
                color: const Color(0xFF9AC0E5).withValues(alpha: 0.42),
              ),
              boxShadow: [
                BoxShadow(
                  color: const Color(0xFF3B6694).withValues(alpha: 0.10),
                  blurRadius: 14,
                  offset: const Offset(0, 5),
                ),
              ],
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 30,
                  height: 30,
                  decoration: BoxDecoration(
                    color: const Color(0xFFEAF3FD),
                    borderRadius: BorderRadius.circular(11),
                  ),
                  child: Icon(
                    shortcut.icon,
                    size: 17,
                    color: const Color(0xFF2F6DB2),
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  shortcut.label,
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: Color(0xFF28415C),
                  ),
                ),
                if (shortcut.badgeCount > 0) ...[
                  const SizedBox(width: 6),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 6,
                      vertical: 1,
                    ),
                    decoration: BoxDecoration(
                      color: const Color(0xFFE05252),
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text(
                      '${shortcut.badgeCount}',
                      style: const TextStyle(
                        fontSize: 10.5,
                        fontWeight: FontWeight.w700,
                        color: Colors.white,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
