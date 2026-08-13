import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'lark_http_client.dart';
import 'voice_file_stub.dart' if (dart.library.io) 'voice_file_io.dart';

void main() {
  runApp(const LarkApp());
}

const _assetLarkSplash = 'assets/lark-q.png';
const _assetLarkIcon = 'assets/lark-icon.png';
const _apiBase = String.fromEnvironment(
  'YUNQUE_API_BASE',
  defaultValue: 'https://worker.lark.irises.me',
);
const _sessionKey = 'yunque_session_cookie';
const _proactiveEnabledKey = 'proactive_reply_enabled';
const _seenAiDiaryBatchesKey = 'seen_ai_diary_v2_batches';

class LarkApp extends StatelessWidget {
  const LarkApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: '云雀',
      theme: ThemeData(
        useMaterial3: true,
        fontFamily: 'PingFang SC',
        scaffoldBackgroundColor: LarkColors.background,
        colorScheme: ColorScheme.fromSeed(
          seedColor: LarkColors.sky,
          surface: Colors.white,
        ),
      ),
      home: const SplashGate(),
    );
  }
}

class SplashGate extends StatefulWidget {
  const SplashGate({super.key});

  @override
  State<SplashGate> createState() => _SplashGateState();
}

class _SplashGateState extends State<SplashGate> {
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    Timer(const Duration(milliseconds: 900), () {
      if (mounted) setState(() => _ready = true);
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_ready) return const LarkHomePage();

    return const Scaffold(
      backgroundColor: Colors.white,
      body: Center(
        child: Image(
          image: AssetImage(_assetLarkSplash),
          width: 230,
          fit: BoxFit.contain,
        ),
      ),
    );
  }
}

enum MainPanel { chat, memory, diary, settings }

enum MemoryLayer { observation, reflection, strategy }

class LarkHomePage extends StatefulWidget {
  const LarkHomePage({super.key});

  @override
  State<LarkHomePage> createState() => _LarkHomePageState();
}

class _LarkHomePageState extends State<LarkHomePage> {
  final _scaffoldKey = GlobalKey<ScaffoldState>();
  final _messageController = TextEditingController();
  final _audioRecorder = AudioRecorder();
  final _client = createLarkHttpClient();
  Timer? _proactiveTimer;
  Timer? _diaryRefreshTimer;

  String? _sessionCookie;
  LarkUser? _user;
  bool _authChecked = false;
  bool _backendOnline = false;
  bool _authBusy = false;
  bool _sending = false;
  bool _proactiveSending = false;
  bool _proactiveEnabled = true;
  bool _diaryCalendarVisible = true;
  bool _loadingData = false;
  bool _memoryLoading = false;
  String? _authError;
  MainPanel _panel = MainPanel.chat;
  DateTime _lastUserInteractionAt = DateTime.now();
  String _selectedUserDiaryDate = _dateKey(DateTime.now());
  MemoryLayer _selectedMemoryLayer = MemoryLayer.observation;

  List<ChatMessage> _messages = [];
  List<DiaryCardData> _diaryCards = [];
  List<String> _userDiaryDates = [];
  Map<MemoryLayer, List<V2MemoryItem>> _memoryLayers = {
    for (final layer in MemoryLayer.values) layer: <V2MemoryItem>[],
  };
  Map<MemoryLayer, int> _memoryUnread = {
    for (final layer in MemoryLayer.values) layer: 0,
  };
  List<AiDiaryBatch> _aiDiaryBatches = [];
  Set<String> _seenAiDiaryBatchIds = {};
  bool _emotionExpanded = false;
  bool _recordingVoice = false;
  EmotionSnapshot _emotion = const EmotionSnapshot(
    textScore: 0,
    fusionScore: 0,
  );

  bool get _isLoggedIn => _user != null;

  Map<String, String> get _headers {
    final headers = {'Content-Type': 'application/json'};
    if (!kIsWeb && _sessionCookie != null && _sessionCookie!.isNotEmpty) {
      headers['Cookie'] = _sessionCookie!;
    }
    return headers;
  }

  @override
  void initState() {
    super.initState();
    _restoreSession();
  }

  void _showStatus(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        behavior: SnackBarBehavior.floating,
        duration: const Duration(seconds: 4),
      ),
    );
  }

  @override
  void dispose() {
    _proactiveTimer?.cancel();
    _diaryRefreshTimer?.cancel();
    _messageController.dispose();
    _audioRecorder.dispose();
    _client.close();
    super.dispose();
  }

  Future<void> _restoreSession() async {
    final prefs = await SharedPreferences.getInstance();
    final savedCookie = prefs.getString(_sessionKey);
    final proactiveEnabled = prefs.getBool(_proactiveEnabledKey) ?? true;
    final seenAiDiaryBatches =
        prefs.getStringList(_seenAiDiaryBatchesKey) ?? const <String>[];
    if (!mounted) return;
    setState(() {
      _sessionCookie = savedCookie;
      _seenAiDiaryBatchIds = seenAiDiaryBatches.toSet();
      _proactiveEnabled = proactiveEnabled;
    });
    await _loadMe();
  }

  Future<void> _loadMe() async {
    try {
      final response = await _client
          .get(Uri.parse('$_apiBase/api/auth/me'), headers: _headers)
          .timeout(const Duration(seconds: 5));
      if (response.statusCode >= 500) {
        throw ApiException(_responseError(response));
      }
      final json = _decodeMap(response.body);
      final userMap = json['user'] as Map<String, dynamic>?;
      if (!mounted) return;
      setState(() {
        _backendOnline = response.statusCode < 500;
        _user = userMap == null ? null : LarkUser.fromJson(userMap);
        _authChecked = true;
      });
      if (_user != null) {
        await _loadUserData();
        _scheduleProactiveReply();
        _scheduleDiaryRefresh();
      }
    } catch (error) {
      debugPrint('loadMe failed: $error');
      if (!mounted) return;
      setState(() {
        _backendOnline = false;
        _authChecked = true;
        _user = null;
      });
    }
  }

  Future<void> _submitAuth({
    required bool register,
    required String username,
    required String password,
  }) async {
    setState(() {
      _authBusy = true;
      _authError = null;
    });
    try {
      final response = await _client
          .post(
            Uri.parse('$_apiBase/api/auth/${register ? 'register' : 'login'}'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'username': username, 'password': password}),
          )
          .timeout(const Duration(seconds: 8));

      final json = _decodeMap(response.body);
      final cookie = _extractSessionCookie(response.headers['set-cookie']);
      final userMap = json['user'] as Map<String, dynamic>?;
      if (response.statusCode >= 400 || userMap == null) {
        throw AuthException(
          _authMessage(json, statusCode: response.statusCode),
        );
      }
      if (!kIsWeb && cookie == null) {
        throw const AuthException('登录成功了，但没有收到会话凭证。请检查 Worker 的 Set-Cookie。');
      }

      final prefs = await SharedPreferences.getInstance();
      if (!kIsWeb && cookie != null) {
        await prefs.setString(_sessionKey, cookie);
      }
      if (!mounted) return;
      setState(() {
        _sessionCookie = cookie ?? _sessionCookie;
        _user = LarkUser.fromJson(userMap);
        _backendOnline = true;
        _authBusy = false;
      });
      await _loadUserData();
      _scheduleProactiveReply();
      _scheduleDiaryRefresh();
    } on AuthException catch (error) {
      if (!mounted) return;
      setState(() {
        _authBusy = false;
        _authError = error.message;
      });
    } catch (error) {
      debugPrint('auth failed: $error');
      if (!mounted) return;
      setState(() {
        _authBusy = false;
        _authError = '暂时连不上云雀服务：$error';
        _backendOnline = false;
      });
    }
  }

  Future<void> _logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_sessionKey);
    if (!mounted) return;
    setState(() {
      _sessionCookie = null;
      _user = null;
      _panel = MainPanel.chat;
      _messages = [];
      _diaryCards = [];
      _userDiaryDates = [];
      _selectedUserDiaryDate = _dateKey(DateTime.now());
      _memoryLayers = {
        for (final layer in MemoryLayer.values) layer: <V2MemoryItem>[],
      };
      _memoryUnread = {for (final layer in MemoryLayer.values) layer: 0};
      _aiDiaryBatches = [];
      _seenAiDiaryBatchIds = {};
      _proactiveTimer?.cancel();
      _diaryRefreshTimer?.cancel();
      _emotion = const EmotionSnapshot(textScore: 0, fusionScore: 0);
    });
  }

  Future<void> _loadUserData() async {
    if (!_isLoggedIn) return;
    setState(() => _loadingData = true);
    await Future.wait([
      _loadChatHistory(),
      _loadDiary(),
      _loadMemories(silent: true),
      _loadAiDiary(),
    ]);
    if (mounted) setState(() => _loadingData = false);
  }

  void _scheduleDiaryRefresh() {
    _diaryRefreshTimer?.cancel();
    if (!_isLoggedIn) return;
    _diaryRefreshTimer = Timer.periodic(const Duration(minutes: 1), (_) {
      _loadAiDiary();
    });
  }

  Future<void> _loadChatHistory() async {
    try {
      final response = await _client
          .get(
            Uri.parse('$_apiBase/api/chat/history?limit=30'),
            headers: _headers,
          )
          .timeout(const Duration(seconds: 6));
      if (response.statusCode >= 400) {
        throw ApiException(_responseError(response));
      }
      final json = _decodeMap(response.body);
      final items = (json['items'] as List<dynamic>? ?? [])
          .whereType<Map<String, dynamic>>()
          .map(ChatMessage.fromHistory)
          .toList();
      if (!mounted) return;
      setState(() {
        _backendOnline = response.statusCode < 500;
        _messages = items.isEmpty
            ? [
                const ChatMessage(
                  fromLark: true,
                  text: '我已经准备好啦。今天想从哪里开始说？',
                  time: '现在',
                ),
              ]
            : items;
      });
    } catch (error) {
      debugPrint('loadChatHistory failed: $error');
      if (!mounted) return;
      setState(() {
        _backendOnline = false;
      });
    }
  }

  Future<void> _loadDiary({String? date, bool hydrateAllDates = true}) async {
    final targetDate = date ?? _selectedUserDiaryDate;
    try {
      final response = await _client
          .get(
            Uri.parse('$_apiBase/api/diary?date=$targetDate'),
            headers: _headers,
          )
          .timeout(const Duration(seconds: 6));
      if (response.statusCode >= 400) {
        throw ApiException(_responseError(response));
      }
      final json = _decodeMap(response.body);
      final selected = json['selected'] as Map<String, dynamic>? ?? {};
      final responseDate = selected['date']?.toString() ?? '';
      if (date != null && responseDate != targetDate) {
        return;
      }
      final dates = _normalizeDiaryDates(json['dates'], selected);
      final selectedByDate = <String, Map<String, dynamic>>{
        if (selected.isNotEmpty)
          (selected['date']?.toString() ?? targetDate): selected,
      };

      if (hydrateAllDates) {
        final missingDates = dates.where(
          (item) => !selectedByDate.containsKey(item),
        );
        final fetched = await Future.wait(
          missingDates.map(_fetchDiarySelected),
        );
        for (final item in fetched) {
          if (item.isEmpty) continue;
          selectedByDate[item['date']?.toString() ?? ''] = item;
        }
      }

      final incomingDiaryCards = selectedByDate.values
          .where(_hasUserDiaryEntry)
          .expand(_buildDiaryCards)
          .toList();
      final nextUserDiaryDates = _sortDiaryDates(
        incomingDiaryCards.map((item) => item.dateLabel),
      );
      final nextDiaryCards = hydrateAllDates
          ? _sortDiaryCards(incomingDiaryCards)
          : _mergedDiaryCardList(_diaryCards, incomingDiaryCards);
      if (!mounted) return;
      if (date != null && targetDate != _selectedUserDiaryDate) {
        return;
      }
      setState(() {
        _backendOnline = response.statusCode < 500;
        _selectedUserDiaryDate = _resolveSelectedDate(
          preferred: _selectedUserDiaryDate,
          availableDates: nextUserDiaryDates,
        );
        _userDiaryDates = hydrateAllDates
            ? nextUserDiaryDates
            : _mergeDiaryDates(_userDiaryDates, nextUserDiaryDates);
        _diaryCards = nextDiaryCards;
      });
    } catch (error) {
      debugPrint('loadDiary failed: $error');
      if (!mounted) return;
      final fallbackUserCards = _fallbackDiaryCards();
      setState(() {
        _backendOnline = false;
        _userDiaryDates = _sortDiaryDates(
          fallbackUserCards.map((item) => item.dateLabel),
        );
        _diaryCards = fallbackUserCards;
      });
    }
  }

  void _selectUserDiaryDate(String date) {
    if (date == _selectedUserDiaryDate) return;
    setState(() => _selectedUserDiaryDate = date);
    _loadDiary(date: date, hydrateAllDates: false);
  }

  Future<void> _saveUserDiary(String date, String markdown) async {
    if (!_isLoggedIn) return;
    final normalized = markdown.trim();
    if (normalized.isEmpty) {
      _showStatus('写点内容再保存。');
      return;
    }
    _applyUserDiaryOptimistically(date, normalized);
    try {
      final response = await _client
          .post(
            Uri.parse('$_apiBase/api/diary/user'),
            headers: _headers,
            body: jsonEncode({'date': date, 'markdown': normalized}),
          )
          .timeout(const Duration(seconds: 8));
      if (response.statusCode >= 400) {
        throw ApiException(_responseError(response));
      }
      final json = _decodeMap(response.body);
      final selected = json['selected'] as Map<String, dynamic>? ?? {};
      if (!mounted) return;
      setState(() {
        _backendOnline = true;
        _selectedUserDiaryDate = date;
        _mergeDiaryCards(_buildDiaryCards(selected));
        _userDiaryDates = _mergeDiaryDates(_userDiaryDates, [date]);
      });
    } catch (error) {
      debugPrint('saveUserDiary failed: $error');
      _showStatus('日记保存失败：$error');
      if (mounted) setState(() => _backendOnline = false);
    }
  }

  Future<Map<String, dynamic>> _fetchDiarySelected(String date) async {
    try {
      final response = await _client
          .get(Uri.parse('$_apiBase/api/diary?date=$date'), headers: _headers)
          .timeout(const Duration(seconds: 6));
      if (response.statusCode >= 400) return {};
      final json = _decodeMap(response.body);
      return json['selected'] as Map<String, dynamic>? ?? {};
    } catch (error) {
      debugPrint('fetchDiarySelected failed: $date $error');
      return {};
    }
  }

  void _applyUserDiaryOptimistically(String date, String markdown) {
    if (!mounted) return;
    final card = DiaryCardData(
      dateLabel: date,
      type: '日记',
      title: _isToday(date) ? '今天的用户记' : '$date 的用户记',
      body: markdown.trim().isEmpty ? '今天还没有写用户记。' : markdown.trim(),
      placeholder: markdown.trim().isEmpty,
    );
    setState(() {
      _selectedUserDiaryDate = date;
      _userDiaryDates = _mergeDiaryDates(_userDiaryDates, [date]);
      _mergeDiaryCards([card]);
    });
  }

  void _mergeDiaryCards(List<DiaryCardData> incoming) {
    final byDate = {for (final item in _diaryCards) item.dateLabel: item};
    for (final item in incoming) {
      byDate[item.dateLabel] = item;
    }
    _diaryCards = _sortDiaryCards(byDate.values);
  }

  List<DiaryCardData> _mergedDiaryCardList(
    List<DiaryCardData> existing,
    List<DiaryCardData> incoming,
  ) {
    final byDate = {for (final item in existing) item.dateLabel: item};
    for (final item in incoming) {
      byDate[item.dateLabel] = item;
    }
    return _sortDiaryCards(byDate.values);
  }

  Future<void> _loadAiDiary() async {
    if (!_isLoggedIn) return;
    try {
      final response = await _client
          .get(Uri.parse('$_apiBase/api/ai-diary/v2'), headers: _headers)
          .timeout(const Duration(seconds: 8));
      if (response.statusCode >= 400) {
        throw ApiException(_responseError(response));
      }
      final json = _decodeMap(response.body);
      final batches = (json['batches'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(AiDiaryBatch.fromJson)
          .toList();
      if (!mounted) return;
      setState(() {
        _backendOnline = true;
        _aiDiaryBatches = batches;
      });
    } catch (error) {
      debugPrint('loadAiDiary failed: $error');
      if (mounted) setState(() => _backendOnline = false);
    }
  }

  Future<void> _loadMemories({bool silent = false}) async {
    if (!_isLoggedIn) return;
    if (!silent) setState(() => _memoryLoading = true);
    try {
      final response = await _client
          .get(Uri.parse('$_apiBase/api/memory/v2'), headers: _headers)
          .timeout(const Duration(seconds: 6));
      if (response.statusCode >= 400) {
        throw ApiException(_responseError(response));
      }
      final json = _decodeMap(response.body);
      if (!mounted) return;
      setState(() {
        _backendOnline = response.statusCode < 500;
        _applyMemoryPayload(json);
      });
    } catch (error) {
      debugPrint('loadMemories failed: $error');
      if (!mounted) return;
      setState(() {
        _backendOnline = false;
      });
    } finally {
      if (mounted && !silent) setState(() => _memoryLoading = false);
    }
  }

  void _applyMemoryPayload(Map<String, dynamic> json) {
    final rawLayers = json['layers'] as Map<String, dynamic>? ?? const {};
    final rawUnread = json['unread'] as Map<String, dynamic>? ?? const {};
    _memoryLayers = {
      for (final layer in MemoryLayer.values)
        layer: (rawLayers[layer.apiName] as List<dynamic>? ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(V2MemoryItem.fromJson)
            .toList(),
    };
    _memoryUnread = {
      for (final layer in MemoryLayer.values)
        layer: _asInt(rawUnread[layer.apiName]),
    };
  }

  Future<void> _markMemoryRead(V2MemoryItem item) async {
    if (!item.isNew) return;
    try {
      final response = await _client
          .post(
            Uri.parse('$_apiBase/api/memory/v2/read'),
            headers: _headers,
            body: jsonEncode({'layer': item.layer.apiName, 'id': item.id}),
          )
          .timeout(const Duration(seconds: 6));
      if (response.statusCode >= 400) return;
      final json = _decodeMap(response.body);
      if (!mounted) return;
      setState(() => _applyMemoryPayload(json));
    } catch (error) {
      debugPrint('markMemoryRead failed: $error');
    }
  }

  Future<void> _markAiDiaryViewed() async {
    final ids = _aiDiaryBatches.map((batch) => batch.batchId).toSet();
    if (ids.difference(_seenAiDiaryBatchIds).isEmpty) return;
    final updated = {..._seenAiDiaryBatchIds, ...ids};
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(_seenAiDiaryBatchesKey, updated.toList());
    if (mounted) setState(() => _seenAiDiaryBatchIds = updated);
  }

  Future<void> _reviewAiDiaryItem(
    AiDiaryBatch batch,
    AiDiaryItem item,
    String action, {
    String revisedContent = '',
  }) async {
    try {
      final response = await _client
          .post(
            Uri.parse('$_apiBase/api/ai-diary/v2/review'),
            headers: _headers,
            body: jsonEncode({
              'batch_id': batch.batchId,
              'observation_id': item.id,
              'action': action,
              if (revisedContent.trim().isNotEmpty)
                'revised_content': revisedContent.trim(),
            }),
          )
          .timeout(const Duration(seconds: 15));
      if (response.statusCode >= 400) {
        throw ApiException(_responseError(response));
      }
      final json = _decodeMap(response.body);
      if (json['ok'] != true) {
        throw ApiException(json['error']?.toString() ?? 'AI记审查失败');
      }
      await Future.wait([_loadAiDiary(), _loadMemories(silent: true)]);
      _showStatus(action == 'confirm' ? '这条 AI记已确认。' : '这条 AI记已修改。');
    } catch (error) {
      debugPrint('reviewAiDiaryItem failed: $error');
      _showStatus('AI记审查失败：$error');
    }
  }

  Future<void> _openAiDiaryCorrection(
    AiDiaryBatch batch,
    AiDiaryItem item,
  ) async {
    final correction = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      backgroundColor: Colors.transparent,
      builder: (context) => AiDiaryCorrectionSheet(item: item),
    );
    if (correction == null || correction.trim().isEmpty) return;
    await _reviewAiDiaryItem(batch, item, 'revise', revisedContent: correction);
  }

  Future<http.Response> _postChatWithRetry(
    Map<String, Object?> payload, {
    required String label,
    Duration timeout = const Duration(seconds: 20),
    int maxAttempts = 3,
  }) async {
    http.Response? lastResponse;
    Object? lastError;
    for (var attempt = 1; attempt <= maxAttempts; attempt += 1) {
      try {
        final response = await _client
            .post(
              Uri.parse('$_apiBase/api/chat'),
              headers: _headers,
              body: jsonEncode(payload),
            )
            .timeout(timeout);
        debugPrint(
          '$label response attempt $attempt: '
          '${response.statusCode} ${_shortBody(response.body)}',
        );
        lastResponse = response;
        if (!_shouldRetryChat(response.statusCode) || attempt == maxAttempts) {
          return response;
        }
      } catch (error) {
        lastError = error;
        debugPrint('$label request attempt $attempt failed: $error');
        if (attempt == maxAttempts) rethrow;
      }
      await Future<void>.delayed(Duration(milliseconds: 450 * attempt));
    }
    if (lastResponse != null) return lastResponse;
    throw lastError ?? const ApiException('聊天请求失败');
  }

  bool _shouldRetryChat(int statusCode) {
    return statusCode == 502 || statusCode == 503 || statusCode == 504;
  }

  Future<void> _sendMessage() async {
    if (!_isLoggedIn) {
      _showStatus('还没有登录成功，先登录一下。');
      return;
    }
    final text = _messageController.text.trim();
    if (text.isEmpty) {
      _showStatus('先输入一句话再发送。');
      return;
    }
    if (_sending) {
      return;
    }
    final time = _shortTime(DateTime.now());
    _lastUserInteractionAt = DateTime.now();
    _scheduleProactiveReply();
    debugPrint('send message start: $text');

    setState(() {
      _sending = true;
      _messages = [
        ..._messages,
        ChatMessage(fromLark: false, text: text, time: time),
      ];
      _messageController.clear();
    });

    try {
      final response = await _postChatWithRetry({
        'message': text,
        'timestamp': DateTime.now().toIso8601String(),
      }, label: 'chat');
      if (response.statusCode >= 400) {
        throw ApiException(_responseError(response));
      }
      final json = _decodeMap(response.body);
      final agent = json['agent'] as Map<String, dynamic>? ?? {};
      final scores = json['scores'] as Map<String, dynamic>? ?? {};
      if (!mounted) return;
      setState(() {
        _backendOnline = response.statusCode < 500;
        _messages = [
          ..._messages,
          ChatMessage(
            fromLark: true,
            text: _nonEmpty(agent['reply']) ?? '我听见了。你可以再多说一点，我会慢慢跟上。',
            time: time,
          ),
        ];
        _emotion = EmotionSnapshot(
          textScore: _asDouble(scores['text']),
          fusionScore: _asDouble(scores['fusion']),
        );
      });
      await Future.wait([
        _loadDiary(),
        _loadMemories(silent: true),
        _loadAiDiary(),
      ]);
    } catch (error) {
      debugPrint('send message failed: $error');
      _showStatus('发送失败：$error');
      if (!mounted) return;
      setState(() {
        _backendOnline = false;
        _messages = [
          ..._messages,
          ChatMessage(fromLark: true, text: '我现在还连不上后端：$error', time: time),
        ];
      });
    } finally {
      if (mounted) {
        setState(() => _sending = false);
        _scheduleProactiveReply();
      }
    }
  }

  Future<void> _toggleVoiceRecording() async {
    if (_sending) return;
    if (_recordingVoice) {
      await _stopAndSendVoice();
      return;
    }
    if (kIsWeb) {
      _showStatus('Flutter Web 预览暂不录音，请使用网页端语音按钮或 Android App。');
      return;
    }
    if (!await _audioRecorder.hasPermission()) {
      _showStatus('需要麦克风权限才能发送语音。');
      return;
    }
    final directory = await getTemporaryDirectory();
    final path =
        '${directory.path}/yunque_${DateTime.now().millisecondsSinceEpoch}.m4a';
    await _audioRecorder.start(
      const RecordConfig(
        encoder: AudioEncoder.aacLc,
        sampleRate: 16000,
        numChannels: 1,
        bitRate: 64000,
      ),
      path: path,
    );
    if (!mounted) return;
    setState(() => _recordingVoice = true);
    _showStatus('正在录音，再点一次麦克风即可发送。');
  }

  Future<void> _stopAndSendVoice() async {
    final path = await _audioRecorder.stop();
    if (mounted) setState(() => _recordingVoice = false);
    if (path == null || path.isEmpty) {
      _showStatus('没有录到有效语音。');
      return;
    }
    try {
      final bytes = await readVoiceFile(path);
      if (bytes.isEmpty) {
        _showStatus('没有录到有效语音。');
        return;
      }
      await _sendVoiceBytes(bytes);
    } finally {
      await deleteVoiceFile(path);
    }
  }

  Future<void> _sendVoiceBytes(List<int> bytes) async {
    if (!_isLoggedIn) {
      _showStatus('还没有登录成功，先登录一下。');
      return;
    }
    final time = _shortTime(DateTime.now());
    _lastUserInteractionAt = DateTime.now();
    setState(() => _sending = true);
    try {
      final response = await _postChatWithRetry(
        {
          'audio_data': 'data:audio/mp4;base64,${base64Encode(bytes)}',
          'timestamp': DateTime.now().toIso8601String(),
        },
        label: 'voice chat',
        timeout: const Duration(seconds: 120),
        maxAttempts: 1,
      );
      if (response.statusCode >= 400) {
        throw ApiException(_responseError(response));
      }
      final json = _decodeMap(response.body);
      final agent = json['agent'] as Map<String, dynamic>? ?? {};
      final scores = json['scores'] as Map<String, dynamic>? ?? {};
      final modalInputs = json['modal_inputs'] as Map<String, dynamic>? ?? {};
      final transcript = _nonEmpty(modalInputs['asr_text']);
      if (transcript == null) throw const ApiException('语音识别没有返回文字');
      if (!mounted) return;
      setState(() {
        _backendOnline = true;
        _messages = [
          ..._messages,
          ChatMessage(fromLark: false, text: '语音：$transcript', time: time),
          ChatMessage(
            fromLark: true,
            text: _nonEmpty(agent['reply']) ?? '我听见了。',
            time: time,
          ),
        ];
        _emotion = EmotionSnapshot(
          textScore: _asDouble(scores['text']),
          fusionScore: _asDouble(scores['fusion']),
        );
      });
      await Future.wait([
        _loadDiary(),
        _loadMemories(silent: true),
        _loadAiDiary(),
      ]);
    } catch (error) {
      _showStatus('语音发送失败：$error');
    } finally {
      if (mounted) setState(() => _sending = false);
      _scheduleProactiveReply();
    }
  }

  void _scheduleProactiveReply() {
    _proactiveTimer?.cancel();
    if (!_isLoggedIn || !_proactiveEnabled) return;
    _proactiveTimer = Timer(const Duration(minutes: 2), () {
      _requestProactiveReply();
    });
  }

  Future<void> _requestProactiveReply() async {
    if (!_isLoggedIn || !_proactiveEnabled || _sending || _proactiveSending) {
      return;
    }
    final idleFor = DateTime.now().difference(_lastUserInteractionAt);
    if (idleFor < const Duration(minutes: 2)) {
      _scheduleProactiveReply();
      return;
    }

    final time = _shortTime(DateTime.now());
    setState(() => _proactiveSending = true);

    try {
      final response = await _postChatWithRetry({
        'message': '',
        'timestamp': DateTime.now().toIso8601String(),
        'proactive': true,
        'proactive_reason': '用户已经安静了一会儿，轻轻发起一句关心。',
      }, label: 'proactive');
      if (response.statusCode >= 400) {
        throw ApiException(_responseError(response));
      }
      final json = _decodeMap(response.body);
      final agent = json['agent'] as Map<String, dynamic>? ?? {};
      final scores = json['scores'] as Map<String, dynamic>? ?? {};
      final reply = _nonEmpty(agent['reply']);
      if (!_proactiveEnabled) return;
      if (!mounted || reply == null) return;
      setState(() {
        _backendOnline = true;
        _messages = [
          ..._messages,
          ChatMessage(fromLark: true, text: reply, time: time),
        ];
        _emotion = EmotionSnapshot(
          textScore: _asDouble(scores['text']),
          fusionScore: _asDouble(scores['fusion']),
        );
      });
      await Future.wait([
        _loadDiary(),
        _loadMemories(silent: true),
        _loadAiDiary(),
      ]);
    } catch (error) {
      debugPrint('proactive reply failed: $error');
    } finally {
      if (mounted) setState(() => _proactiveSending = false);
      _lastUserInteractionAt = DateTime.now();
      _scheduleProactiveReply();
    }
  }

  Future<void> _setProactiveEnabled(bool enabled) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_proactiveEnabledKey, enabled);
    if (!mounted) return;
    setState(() => _proactiveEnabled = enabled);
    if (enabled) {
      _lastUserInteractionAt = DateTime.now();
      _scheduleProactiveReply();
    } else {
      _proactiveTimer?.cancel();
      if (_proactiveSending) {
        setState(() => _proactiveSending = false);
      }
    }
  }

  void _clearCache() {
    setState(() {
      _messages = [
        const ChatMessage(
          fromLark: true,
          text: '本地聊天缓存已经清掉啦。我们可以重新开始。',
          time: '现在',
        ),
      ];
      _emotion = const EmotionSnapshot(textScore: 0, fusionScore: 0);
    });
  }

  void _openPanel(MainPanel panel) {
    Navigator.of(context).maybePop();
    setState(() => _panel = panel);
    if (panel == MainPanel.diary) {
      _markAiDiaryViewed();
    }
  }

  int get _memoryUnreadTotal =>
      _memoryUnread.values.fold(0, (total, count) => total + count);

  int get _aiDiaryNewCount => _aiDiaryBatches
      .where((batch) => !_seenAiDiaryBatchIds.contains(batch.batchId))
      .length;

  String get _headerTitle {
    return switch (_panel) {
      MainPanel.chat => '云雀',
      MainPanel.memory => '记忆',
      MainPanel.diary => '日记',
      MainPanel.settings => '设置',
    };
  }

  @override
  Widget build(BuildContext context) {
    final locked = !_authChecked || !_isLoggedIn;
    return Scaffold(
      key: _scaffoldKey,
      drawer: LarkDrawer(
        selected: _panel,
        user: _user,
        onOpenChat: () => _openPanel(MainPanel.chat),
        onOpenMemory: () => _openPanel(MainPanel.memory),
        onOpenDiary: () => _openPanel(MainPanel.diary),
        onOpenSettings: () => _openPanel(MainPanel.settings),
        memoryNewCount: _memoryUnreadTotal,
        diaryNewCount: _aiDiaryNewCount,
        onLogout: _logout,
      ),
      body: SafeArea(
        child: Stack(
          children: [
            Column(
              children: [
                LarkHeader(
                  title: _headerTitle,
                  online: _panel == MainPanel.chat ? _backendOnline : null,
                  action: _panel == MainPanel.diary
                      ? IconButton(
                          tooltip: _diaryCalendarVisible ? '隐藏日历' : '显示日历',
                          onPressed: () {
                            setState(() {
                              _diaryCalendarVisible = !_diaryCalendarVisible;
                            });
                          },
                          icon: Icon(
                            _diaryCalendarVisible
                                ? Icons.calendar_month_rounded
                                : Icons.calendar_today_outlined,
                          ),
                          color: LarkColors.text,
                        )
                      : null,
                  onMenuTap: () => _scaffoldKey.currentState?.openDrawer(),
                ),
                if (_loadingData) const LinearProgressIndicator(minHeight: 2),
                Expanded(child: _buildMainPanel()),
              ],
            ),
            if (locked)
              AuthGate(
                checked: _authChecked,
                busy: _authBusy,
                error: _authError,
                onSubmit: _submitAuth,
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildMainPanel() {
    return switch (_panel) {
      MainPanel.chat => ChatPage(
        messages: _messages,
        typing: _sending || _proactiveSending,
        sending: _sending,
        messageController: _messageController,
        emotion: _emotion,
        emotionExpanded: _emotionExpanded,
        onEmotionToggle: () {
          setState(() => _emotionExpanded = !_emotionExpanded);
        },
        onSend: _sendMessage,
        recordingVoice: _recordingVoice,
        onVoice: _toggleVoiceRecording,
        onClearCache: _clearCache,
      ),
      MainPanel.memory => MemoryPage(
        layers: _memoryLayers,
        unread: _memoryUnread,
        selectedLayer: _selectedMemoryLayer,
        loading: _memoryLoading,
        onLayerSelected: (layer) {
          setState(() => _selectedMemoryLayer = layer);
        },
        onItemOpened: _markMemoryRead,
      ),
      MainPanel.diary => JournalPage(
        userCards: _diaryCards,
        aiBatches: _aiDiaryBatches,
        userDates: _userDiaryDates,
        selectedUserDate: _selectedUserDiaryDate,
        calendarVisible: _diaryCalendarVisible,
        onEdit: _openDiaryEditor,
        onDelete: _deleteUserDiary,
        onUserDateSelected: _selectUserDiaryDate,
        onAiConfirm: (batch, item) =>
            _reviewAiDiaryItem(batch, item, 'confirm'),
        onAiCorrect: _openAiDiaryCorrection,
      ),
      MainPanel.settings => SettingsPage(
        proactiveEnabled: _proactiveEnabled,
        onProactiveChanged: _setProactiveEnabled,
      ),
    };
  }

  Future<void> _openDiaryEditor([DiaryCardData? card]) async {
    final date = card?.dateLabel ?? _selectedUserDiaryDate;
    final initialText = card == null || card.placeholder ? '' : card.body;
    final saved = await showDialog<String>(
      context: context,
      builder: (context) =>
          DiaryEditorDialog(date: date, initialText: initialText),
    );
    if (saved == null) return;
    await _saveUserDiary(date, saved);
  }

  Future<void> _deleteUserDiary(DiaryCardData card) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除这篇日记？'),
        content: Text('${card.dateLabel} 的用户日记会从存储里删除。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: FilledButton.styleFrom(backgroundColor: LarkColors.offline),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed != true || !_isLoggedIn) return;
    try {
      final response = await _client
          .post(
            Uri.parse('$_apiBase/api/diary/user/delete'),
            headers: _headers,
            body: jsonEncode({'date': card.dateLabel}),
          )
          .timeout(const Duration(seconds: 8));
      if (response.statusCode >= 400) {
        throw ApiException(_responseError(response));
      }
      if (!mounted) return;
      setState(() {
        final diaryByDate = {
          for (final item in _diaryCards)
            if (item.dateLabel != card.dateLabel) item.dateLabel: item,
        };
        _backendOnline = true;
        _selectedUserDiaryDate = card.dateLabel;
        _userDiaryDates = _sortDiaryDates(diaryByDate.keys);
        _diaryCards = _sortDiaryCards(diaryByDate.values);
      });
      _showStatus('日记已删除。');
    } catch (error) {
      debugPrint('deleteUserDiary failed: $error');
      _showStatus('日记删除失败：$error');
      if (mounted) setState(() => _backendOnline = false);
    }
  }
}

class AuthGate extends StatefulWidget {
  const AuthGate({
    required this.checked,
    required this.busy,
    required this.error,
    required this.onSubmit,
    super.key,
  });

  final bool checked;
  final bool busy;
  final String? error;
  final Future<void> Function({
    required bool register,
    required String username,
    required String password,
  })
  onSubmit;

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _register = false;

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final username = _usernameController.text.trim();
    final password = _passwordController.text;
    if (username.isEmpty || password.length < 8 || widget.busy) return;
    await widget.onSubmit(
      register: _register,
      username: username,
      password: password,
    );
  }

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: Colors.white.withValues(alpha: 0.94),
      child: Center(
        child: widget.checked
            ? SingleChildScrollView(
                padding: const EdgeInsets.all(24),
                child: Container(
                  constraints: const BoxConstraints(maxWidth: 380),
                  padding: const EdgeInsets.all(22),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(22),
                    border: Border.all(color: LarkColors.line),
                    boxShadow: const [
                      BoxShadow(
                        color: Color(0x1679BCEB),
                        blurRadius: 28,
                        offset: Offset(0, 14),
                      ),
                    ],
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Image(
                        image: AssetImage(_assetLarkIcon),
                        width: 88,
                        height: 88,
                      ),
                      const SizedBox(height: 14),
                      Text(
                        _register ? '注册云雀' : '登录云雀',
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          fontSize: 24,
                          fontWeight: FontWeight.w900,
                          color: LarkColors.text,
                        ),
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        '登录后会记住你的聊天记录、日记和长期记忆。',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: LarkColors.subtle, height: 1.4),
                      ),
                      const SizedBox(height: 20),
                      TextField(
                        controller: _usernameController,
                        textInputAction: TextInputAction.next,
                        decoration: const InputDecoration(
                          labelText: '用户名',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: _passwordController,
                        obscureText: true,
                        onSubmitted: (_) => _submit(),
                        decoration: const InputDecoration(
                          labelText: '密码',
                          helperText: '至少 8 位',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      if (widget.error != null) ...[
                        const SizedBox(height: 10),
                        Text(
                          widget.error!,
                          style: const TextStyle(color: LarkColors.offline),
                        ),
                      ],
                      const SizedBox(height: 16),
                      FilledButton(
                        onPressed: widget.busy ? null : _submit,
                        style: FilledButton.styleFrom(
                          backgroundColor: LarkColors.sky,
                          minimumSize: const Size.fromHeight(48),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(15),
                          ),
                        ),
                        child: widget.busy
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : Text(_register ? '注册并进入' : '登录'),
                      ),
                      TextButton(
                        onPressed: widget.busy
                            ? null
                            : () => setState(() => _register = !_register),
                        child: Text(_register ? '已有账号，去登录' : '没有账号，先注册'),
                      ),
                    ],
                  ),
                ),
              )
            : const CircularProgressIndicator(color: LarkColors.sky),
      ),
    );
  }
}

class LarkHeader extends StatelessWidget {
  const LarkHeader({
    required this.title,
    required this.online,
    required this.onMenuTap,
    this.action,
    super.key,
  });

  final String title;
  final bool? online;
  final VoidCallback onMenuTap;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 62,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.96),
        border: const Border(bottom: BorderSide(color: LarkColors.line)),
      ),
      child: Row(
        children: [
          IconButton(
            tooltip: '侧边栏',
            onPressed: onMenuTap,
            icon: const Icon(Icons.menu_open_rounded),
            color: LarkColors.text,
          ),
          Expanded(
            child: Text(
              title,
              style: const TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w800,
                color: LarkColors.text,
              ),
            ),
          ),
          if (action != null)
            action!
          else if (online != null) ...[
            Container(
              width: 9,
              height: 9,
              decoration: BoxDecoration(
                color: online! ? LarkColors.online : LarkColors.offline,
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: 6),
            Text(
              online! ? '在线' : '离线',
              style: const TextStyle(
                fontSize: 13,
                color: LarkColors.subtle,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class LarkDrawer extends StatelessWidget {
  const LarkDrawer({
    required this.selected,
    required this.user,
    required this.onOpenChat,
    required this.onOpenMemory,
    required this.onOpenDiary,
    required this.onOpenSettings,
    required this.memoryNewCount,
    required this.diaryNewCount,
    required this.onLogout,
    super.key,
  });

  final MainPanel selected;
  final LarkUser? user;
  final VoidCallback onOpenChat;
  final VoidCallback onOpenMemory;
  final VoidCallback onOpenDiary;
  final VoidCallback onOpenSettings;
  final int memoryNewCount;
  final int diaryNewCount;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    return Drawer(
      backgroundColor: Colors.white,
      child: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
              child: Row(
                children: [
                  const CircleAvatar(
                    radius: 24,
                    backgroundColor: LarkColors.softBlue,
                    backgroundImage: AssetImage(_assetLarkIcon),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          '云雀',
                          style: TextStyle(
                            fontWeight: FontWeight.w900,
                            fontSize: 18,
                            color: LarkColors.text,
                          ),
                        ),
                        Text(
                          user?.username ?? '未登录',
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(color: LarkColors.subtle),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            DrawerRow(
              selected: selected == MainPanel.chat,
              icon: Icons.chat_bubble_outline_rounded,
              title: '聊天',
              onTap: onOpenChat,
            ),
            DrawerRow(
              selected: selected == MainPanel.memory,
              icon: Icons.psychology_alt_outlined,
              title: '记忆',
              newCount: memoryNewCount,
              onTap: onOpenMemory,
            ),
            DrawerRow(
              selected: selected == MainPanel.diary,
              icon: Icons.edit_note_rounded,
              title: '日记',
              newCount: diaryNewCount,
              onTap: onOpenDiary,
            ),
            DrawerRow(
              selected: selected == MainPanel.settings,
              icon: Icons.settings_rounded,
              title: '设置',
              onTap: onOpenSettings,
            ),
            const Spacer(),
            Padding(
              padding: const EdgeInsets.all(12),
              child: TextButton.icon(
                onPressed: onLogout,
                icon: const Icon(Icons.logout_rounded),
                label: const Text('退出登录'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class DrawerRow extends StatelessWidget {
  const DrawerRow({
    required this.selected,
    required this.icon,
    required this.title,
    required this.onTap,
    this.newCount = 0,
    super.key,
  });

  final bool selected;
  final IconData icon;
  final String title;
  final VoidCallback onTap;
  final int newCount;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Material(
        color: selected ? LarkColors.softBlue : Colors.transparent,
        borderRadius: BorderRadius.circular(14),
        child: ListTile(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
          ),
          leading: Icon(
            icon,
            color: selected ? LarkColors.sky : LarkColors.subtle,
          ),
          title: Text(
            title,
            style: TextStyle(
              color: LarkColors.text,
              fontWeight: selected ? FontWeight.w900 : FontWeight.w700,
            ),
          ),
          trailing: newCount > 0
              ? _NewBadge(count: newCount)
              : const Icon(Icons.chevron_right_rounded),
          onTap: onTap,
        ),
      ),
    );
  }
}

class _NewBadge extends StatelessWidget {
  const _NewBadge({this.count});

  final int? count;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF0D6),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        count == null ? 'NEW' : 'NEW ${count!}',
        style: const TextStyle(
          color: Color(0xFF9A6821),
          fontSize: 10,
          fontWeight: FontWeight.w900,
        ),
      ),
    );
  }
}

class ChatPage extends StatelessWidget {
  const ChatPage({
    required this.messages,
    required this.typing,
    required this.sending,
    required this.messageController,
    required this.emotion,
    required this.emotionExpanded,
    required this.onEmotionToggle,
    required this.onSend,
    required this.recordingVoice,
    required this.onVoice,
    required this.onClearCache,
    super.key,
  });

  final List<ChatMessage> messages;
  final bool typing;
  final bool sending;
  final TextEditingController messageController;
  final EmotionSnapshot emotion;
  final bool emotionExpanded;
  final VoidCallback onEmotionToggle;
  final VoidCallback onSend;
  final bool recordingVoice;
  final VoidCallback onVoice;
  final VoidCallback onClearCache;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Colors.white, LarkColors.background],
        ),
      ),
      child: Stack(
        children: [
          Column(
            children: [
              Expanded(
                child: ListView.builder(
                  padding: const EdgeInsets.fromLTRB(14, 76, 14, 8),
                  itemCount: messages.length + (typing ? 1 : 0),
                  itemBuilder: (context, index) {
                    if (index == messages.length) {
                      return const TypingBubble();
                    }
                    return MessageBubble(message: messages[index]);
                  },
                ),
              ),
              ChatComposer(
                controller: messageController,
                sending: sending,
                onSend: onSend,
                recordingVoice: recordingVoice,
                onVoice: onVoice,
                onClearCache: onClearCache,
              ),
            ],
          ),
          Positioned(
            top: 10,
            right: 12,
            child: EmotionMiniPanel(
              snapshot: emotion,
              expanded: emotionExpanded,
              onToggle: onEmotionToggle,
            ),
          ),
        ],
      ),
    );
  }
}

class EmotionMiniPanel extends StatelessWidget {
  const EmotionMiniPanel({
    required this.snapshot,
    required this.expanded,
    required this.onToggle,
    super.key,
  });

  final EmotionSnapshot snapshot;
  final bool expanded;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white.withValues(alpha: 0.96),
      elevation: 3,
      shadowColor: const Color(0x220A4E75),
      borderRadius: BorderRadius.circular(16),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 220),
        width: expanded ? 220 : 112,
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          border: Border.all(color: LarkColors.line),
          borderRadius: BorderRadius.circular(16),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            InkWell(
              onTap: onToggle,
              borderRadius: BorderRadius.circular(12),
              child: Row(
                children: [
                  const Icon(
                    Icons.monitor_heart_outlined,
                    size: 18,
                    color: LarkColors.sky,
                  ),
                  const SizedBox(width: 6),
                  const Expanded(
                    child: Text(
                      '情绪画像',
                      style: TextStyle(
                        color: LarkColors.text,
                        fontSize: 12,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ),
                  Icon(
                    expanded
                        ? Icons.keyboard_arrow_up_rounded
                        : Icons.keyboard_arrow_down_rounded,
                    size: 18,
                    color: LarkColors.subtle,
                  ),
                ],
              ),
            ),
            if (expanded) ...[
              const Divider(height: 16),
              _EmotionScoreRow(label: '文本模态', value: snapshot.textScore),
              const SizedBox(height: 7),
              _EmotionScoreRow(label: '融合得分', value: snapshot.fusionScore),
            ],
          ],
        ),
      ),
    );
  }
}

class _EmotionScoreRow extends StatelessWidget {
  const _EmotionScoreRow({required this.label, required this.value});

  final String label;
  final double value;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Text(
            label,
            style: const TextStyle(color: LarkColors.subtle, fontSize: 12),
          ),
        ),
        Text(
          value.toStringAsFixed(2),
          style: const TextStyle(
            color: LarkColors.text,
            fontWeight: FontWeight.w900,
          ),
        ),
      ],
    );
  }
}

class MessageBubble extends StatelessWidget {
  const MessageBubble({required this.message, super.key});

  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final isLark = message.fromLark;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: isLark
            ? MainAxisAlignment.start
            : MainAxisAlignment.end,
        children: [
          if (isLark) ...[
            const CircleAvatar(
              radius: 20,
              backgroundColor: LarkColors.softBlue,
              backgroundImage: AssetImage(_assetLarkIcon),
            ),
            const SizedBox(width: 9),
          ],
          Flexible(
            child: Column(
              crossAxisAlignment: isLark
                  ? CrossAxisAlignment.start
                  : CrossAxisAlignment.end,
              children: [
                Container(
                  constraints: const BoxConstraints(maxWidth: 280),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 11,
                  ),
                  decoration: BoxDecoration(
                    color: isLark ? Colors.white : LarkColors.sky,
                    borderRadius: BorderRadius.only(
                      topLeft: const Radius.circular(16),
                      topRight: const Radius.circular(16),
                      bottomLeft: Radius.circular(isLark ? 4 : 16),
                      bottomRight: Radius.circular(isLark ? 16 : 4),
                    ),
                    border: Border.all(
                      color: isLark ? LarkColors.line : LarkColors.sky,
                    ),
                    boxShadow: const [
                      BoxShadow(
                        color: Color(0x100A4E75),
                        blurRadius: 14,
                        offset: Offset(0, 5),
                      ),
                    ],
                  ),
                  child: Text(
                    message.text,
                    style: TextStyle(
                      height: 1.45,
                      fontSize: 15,
                      color: isLark ? LarkColors.text : Colors.white,
                    ),
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  message.time,
                  style: const TextStyle(color: LarkColors.muted, fontSize: 11),
                ),
              ],
            ),
          ),
          if (!isLark) const SizedBox(width: 44),
        ],
      ),
    );
  }
}

class TypingBubble extends StatelessWidget {
  const TypingBubble({super.key});

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.only(bottom: 14),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CircleAvatar(
            radius: 20,
            backgroundColor: LarkColors.softBlue,
            backgroundImage: AssetImage(_assetLarkIcon),
          ),
          SizedBox(width: 9),
          Flexible(
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.only(
                  topLeft: Radius.circular(16),
                  topRight: Radius.circular(16),
                  bottomLeft: Radius.circular(4),
                  bottomRight: Radius.circular(16),
                ),
                border: Border.fromBorderSide(
                  BorderSide(color: LarkColors.line),
                ),
                boxShadow: [
                  BoxShadow(
                    color: Color(0x100A4E75),
                    blurRadius: 14,
                    offset: Offset(0, 5),
                  ),
                ],
              ),
              child: Padding(
                padding: EdgeInsets.symmetric(horizontal: 14, vertical: 11),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      '正在输入中',
                      style: TextStyle(color: LarkColors.subtle, fontSize: 15),
                    ),
                    AnimatedDots(),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class AnimatedDots extends StatefulWidget {
  const AnimatedDots({super.key});

  @override
  State<AnimatedDots> createState() => _AnimatedDotsState();
}

class _AnimatedDotsState extends State<AnimatedDots>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) {
        return Row(
          mainAxisSize: MainAxisSize.min,
          children: List.generate(3, (index) {
            final phase = (_controller.value * 3 - index).clamp(0.0, 1.0);
            final offset = -4.0 * (1 - (phase * 2 - 1).abs()).clamp(0.0, 1.0);
            return Transform.translate(
              offset: Offset(0, offset),
              child: const Text(
                '.',
                style: TextStyle(
                  color: LarkColors.subtle,
                  fontSize: 18,
                  fontWeight: FontWeight.w800,
                ),
              ),
            );
          }),
        );
      },
    );
  }
}

class ChatComposer extends StatelessWidget {
  const ChatComposer({
    required this.controller,
    required this.sending,
    required this.onSend,
    required this.recordingVoice,
    required this.onVoice,
    required this.onClearCache,
    super.key,
  });

  final TextEditingController controller;
  final bool sending;
  final VoidCallback onSend;
  final bool recordingVoice;
  final VoidCallback onVoice;
  final VoidCallback onClearCache;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 14),
      color: LarkColors.background,
      child: Row(
        children: [
          Expanded(
            child: Container(
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.94),
                borderRadius: BorderRadius.circular(18),
                border: Border.all(color: LarkColors.line),
              ),
              child: Row(
                children: [
                  IconButton(
                    tooltip: recordingVoice ? '停止并发送录音' : '发送语音',
                    onPressed: sending ? null : onVoice,
                    icon: Icon(
                      recordingVoice ? Icons.stop_rounded : Icons.mic_rounded,
                    ),
                    color: recordingVoice
                        ? Colors.redAccent
                        : LarkColors.subtle,
                  ),
                  IconButton(
                    tooltip: '清理缓存',
                    onPressed: onClearCache,
                    icon: const Icon(Icons.cleaning_services_rounded),
                    color: LarkColors.subtle,
                  ),
                  Expanded(
                    child: TextField(
                      controller: controller,
                      minLines: 1,
                      maxLines: 4,
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => onSend(),
                      decoration: const InputDecoration(
                        hintText: '和云雀说点什么',
                        border: InputBorder.none,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(width: 10),
          SizedBox(
            width: 48,
            height: 48,
            child: FilledButton(
              onPressed: sending ? null : onSend,
              style: FilledButton.styleFrom(
                padding: EdgeInsets.zero,
                backgroundColor: LarkColors.sky,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
              ),
              child: sending
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : const Icon(Icons.arrow_upward_rounded),
            ),
          ),
        ],
      ),
    );
  }
}

class SettingsPage extends StatelessWidget {
  const SettingsPage({
    required this.proactiveEnabled,
    required this.onProactiveChanged,
    super.key,
  });

  final bool proactiveEnabled;
  final ValueChanged<bool> onProactiveChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: LarkColors.background,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(18, 18, 18, 28),
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: LarkColors.line),
            ),
            child: SwitchListTile(
              value: proactiveEnabled,
              onChanged: onProactiveChanged,
              contentPadding: EdgeInsets.zero,
              activeThumbColor: LarkColors.sky,
              title: const Text(
                '主动回应',
                style: TextStyle(
                  color: LarkColors.text,
                  fontWeight: FontWeight.w900,
                ),
              ),
              subtitle: Text(
                proactiveEnabled ? '云雀会在你安静一会儿后轻轻回应。' : '云雀只会在你发消息后回应。',
                style: const TextStyle(color: LarkColors.subtle),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class MemoryPage extends StatelessWidget {
  const MemoryPage({
    required this.layers,
    required this.unread,
    required this.selectedLayer,
    required this.loading,
    required this.onLayerSelected,
    required this.onItemOpened,
    super.key,
  });

  final Map<MemoryLayer, List<V2MemoryItem>> layers;
  final Map<MemoryLayer, int> unread;
  final MemoryLayer selectedLayer;
  final bool loading;
  final ValueChanged<MemoryLayer> onLayerSelected;
  final ValueChanged<V2MemoryItem> onItemOpened;

  @override
  Widget build(BuildContext context) {
    final items = layers[selectedLayer] ?? const <V2MemoryItem>[];
    return Container(
      color: LarkColors.background,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 14, 14, 8),
            child: Row(
              children: MemoryLayer.values.map((layer) {
                final selected = layer == selectedLayer;
                final newCount = unread[layer] ?? 0;
                return Expanded(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 3),
                    child: Material(
                      color: selected ? LarkColors.sky : Colors.white,
                      borderRadius: BorderRadius.circular(16),
                      child: InkWell(
                        onTap: () => onLayerSelected(layer),
                        borderRadius: BorderRadius.circular(16),
                        child: Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 12,
                          ),
                          child: Column(
                            children: [
                              Icon(
                                layer.icon,
                                color: selected
                                    ? Colors.white
                                    : LarkColors.subtle,
                              ),
                              const SizedBox(height: 5),
                              Text(
                                layer.label,
                                style: TextStyle(
                                  color: selected
                                      ? Colors.white
                                      : LarkColors.text,
                                  fontWeight: FontWeight.w900,
                                ),
                              ),
                              if (newCount > 0) ...[
                                const SizedBox(height: 5),
                                _NewBadge(count: newCount),
                              ],
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
                );
              }).toList(),
            ),
          ),
          if (loading) const LinearProgressIndicator(minHeight: 2),
          Expanded(
            child: items.isEmpty
                ? Center(
                    child: Text(
                      '还没有${selectedLayer.label}记忆。',
                      style: const TextStyle(color: LarkColors.subtle),
                    ),
                  )
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(14, 6, 14, 24),
                    itemCount: items.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 10),
                    itemBuilder: (context, index) {
                      final item = items[index];
                      return MemoryCard(
                        item: item,
                        onTap: () {
                          onItemOpened(item);
                          showModalBottomSheet<void>(
                            context: context,
                            useSafeArea: true,
                            showDragHandle: true,
                            builder: (context) => MemoryDetail(item: item),
                          );
                        },
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

class MemoryCard extends StatelessWidget {
  const MemoryCard({required this.item, required this.onTap, super.key});

  final V2MemoryItem item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(18),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: Container(
          padding: const EdgeInsets.all(15),
          decoration: BoxDecoration(
            border: Border.all(color: LarkColors.line),
            borderRadius: BorderRadius.circular(18),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      item.id,
                      style: const TextStyle(
                        color: LarkColors.text,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ),
                  if (item.isNew) const _NewBadge(),
                ],
              ),
              const SizedBox(height: 9),
              Text(
                item.description,
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: LarkColors.text, height: 1.5),
              ),
              if (item.topics.isNotEmpty) ...[
                const SizedBox(height: 10),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: item.topics
                      .map((topic) => _TopicChip(label: topic))
                      .toList(),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class MemoryDetail extends StatelessWidget {
  const MemoryDetail({required this.item, super.key});

  final V2MemoryItem item;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 28),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            item.id,
            style: const TextStyle(
              color: LarkColors.text,
              fontSize: 21,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 12),
          Text(
            item.description,
            style: const TextStyle(
              color: LarkColors.text,
              fontSize: 16,
              height: 1.55,
            ),
          ),
          if (item.scene.isNotEmpty) ...[
            const SizedBox(height: 14),
            Text(
              '适用场景：${item.scene}',
              style: const TextStyle(color: LarkColors.subtle),
            ),
          ],
          const SizedBox(height: 14),
          Text(
            '重要度 ${item.importance.toStringAsFixed(1)} · '
            '置信度 ${item.confidence.toStringAsFixed(1)}',
            style: const TextStyle(color: LarkColors.subtle),
          ),
          if (item.linkedMemoryIds.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              '关联记忆：${item.linkedMemoryIds.join('、')}',
              style: const TextStyle(color: LarkColors.subtle),
            ),
          ],
        ],
      ),
    );
  }
}

class _TopicChip extends StatelessWidget {
  const _TopicChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: LarkColors.softBlue,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        _topicLabel(label),
        style: const TextStyle(
          color: LarkColors.subtle,
          fontSize: 11,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class JournalPage extends StatefulWidget {
  const JournalPage({
    required this.userCards,
    required this.aiBatches,
    required this.userDates,
    required this.selectedUserDate,
    required this.calendarVisible,
    this.onEdit,
    this.onDelete,
    this.onUserDateSelected,
    this.onAiConfirm,
    this.onAiCorrect,
    super.key,
  });

  final List<DiaryCardData> userCards;
  final List<AiDiaryBatch> aiBatches;
  final List<String> userDates;
  final String selectedUserDate;
  final bool calendarVisible;
  final ValueChanged<DiaryCardData?>? onEdit;
  final ValueChanged<DiaryCardData>? onDelete;
  final ValueChanged<String>? onUserDateSelected;
  final void Function(AiDiaryBatch, AiDiaryItem)? onAiConfirm;
  final void Function(AiDiaryBatch, AiDiaryItem)? onAiCorrect;

  @override
  State<JournalPage> createState() => _JournalPageState();
}

class _JournalPageState extends State<JournalPage> {
  int _pageIndex = 0;

  void _showPage(int index) {
    setState(() => _pageIndex = index);
  }

  Widget _buildTabButton(String label, int index) {
    final selected = _pageIndex == index;
    return Expanded(
      child: TextButton(
        onPressed: () => _showPage(index),
        style: TextButton.styleFrom(
          foregroundColor: selected ? Colors.white : LarkColors.subtle,
          backgroundColor: selected ? LarkColors.sky : Colors.transparent,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
          ),
          padding: const EdgeInsets.symmetric(vertical: 10),
        ),
        child: Text(label, style: const TextStyle(fontWeight: FontWeight.w900)),
      ),
    );
  }

  Future<void> _showUserDiaryActions(DiaryCardData card) async {
    final action = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(card.dateLabel),
        content: const Text('选择要对这篇用户日记做什么。'),
        actions: [
          TextButton.icon(
            onPressed: () => Navigator.of(context).pop('edit'),
            icon: const Icon(Icons.edit_rounded),
            label: const Text('编辑'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.of(context).pop('delete'),
            style: FilledButton.styleFrom(backgroundColor: LarkColors.offline),
            icon: const Icon(Icons.delete_outline_rounded),
            label: const Text('删除'),
          ),
        ],
      ),
    );
    if (action == 'edit') {
      widget.onEdit?.call(card);
    } else if (action == 'delete') {
      widget.onDelete?.call(card);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      color: LarkColors.background,
      child: Stack(
        children: [
          Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 0),
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(4),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(color: LarkColors.line),
                  ),
                  child: Row(
                    children: [
                      _buildTabButton('用户日记', 0),
                      const SizedBox(width: 4),
                      _buildTabButton('AI记', 1),
                    ],
                  ),
                ),
              ),
              if (_pageIndex == 0)
                AnimatedSwitcher(
                  duration: const Duration(milliseconds: 220),
                  child: widget.calendarVisible
                      ? MiniCalendar(
                          dates: widget.userDates,
                          selectedDate: widget.selectedUserDate,
                          onDateSelected: widget.onUserDateSelected,
                        )
                      : const SizedBox.shrink(key: ValueKey('calendar-hidden')),
                ),
              Expanded(
                child: _pageIndex == 0
                    ? _UserDiaryList(
                        cards: widget.userCards,
                        selectedDate: widget.selectedUserDate,
                        onLongPress: _showUserDiaryActions,
                      )
                    : AiDiaryList(
                        batches: widget.aiBatches,
                        onConfirm: widget.onAiConfirm,
                        onCorrect: widget.onAiCorrect,
                      ),
              ),
            ],
          ),
          if (_pageIndex == 0)
            Positioned(
              left: 16,
              right: 16,
              bottom: 16,
              child: SafeArea(
                top: false,
                child: FilledButton.icon(
                  onPressed: () => widget.onEdit?.call(null),
                  style: FilledButton.styleFrom(
                    backgroundColor: LarkColors.sky,
                    minimumSize: const Size.fromHeight(52),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(18),
                    ),
                  ),
                  icon: const Icon(Icons.edit_rounded),
                  label: const Text(
                    '写日记',
                    style: TextStyle(fontWeight: FontWeight.w800),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _UserDiaryList extends StatelessWidget {
  const _UserDiaryList({
    required this.cards,
    required this.selectedDate,
    required this.onLongPress,
  });

  final List<DiaryCardData> cards;
  final String selectedDate;
  final ValueChanged<DiaryCardData> onLongPress;

  @override
  Widget build(BuildContext context) {
    if (cards.isEmpty) {
      return const Center(
        child: Text(
          '这里会按时间顺序展示你的用户日记。',
          style: TextStyle(color: LarkColors.subtle),
        ),
      );
    }
    return ListView.separated(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 96),
      itemCount: cards.length,
      separatorBuilder: (_, _) => const SizedBox(height: 12),
      itemBuilder: (context, index) {
        final card = cards[index];
        return DiaryCard(
          data: card,
          selected: card.dateLabel == selectedDate,
          onLongPress: () => onLongPress(card),
        );
      },
    );
  }
}

class AiDiaryList extends StatelessWidget {
  const AiDiaryList({
    required this.batches,
    required this.onConfirm,
    required this.onCorrect,
    super.key,
  });

  final List<AiDiaryBatch> batches;
  final void Function(AiDiaryBatch, AiDiaryItem)? onConfirm;
  final void Function(AiDiaryBatch, AiDiaryItem)? onCorrect;

  @override
  Widget build(BuildContext context) {
    if (batches.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(28),
          child: Text(
            '每生成三条观察后，云雀会在这里整理一组 AI记。',
            textAlign: TextAlign.center,
            style: TextStyle(color: LarkColors.subtle),
          ),
        ),
      );
    }
    return ListView.separated(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 28),
      itemCount: batches.length,
      separatorBuilder: (_, _) => const SizedBox(height: 14),
      itemBuilder: (context, index) {
        final batch = batches[index];
        return Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: Colors.white,
            border: Border.all(color: LarkColors.line),
            borderRadius: BorderRadius.circular(20),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(
                    Icons.auto_stories_outlined,
                    color: LarkColors.sky,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      '${batch.dateKey} · ${batch.batchId}',
                      style: const TextStyle(
                        color: LarkColors.text,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ),
                  if (batch.pendingCount > 0)
                    Text(
                      '待审查 ${batch.pendingCount}',
                      style: const TextStyle(
                        color: Color(0xFF9A6821),
                        fontSize: 12,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 10),
              ...batch.items.map(
                (item) => Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: AiDiaryItemCard(
                    item: item,
                    onConfirm: item.pending
                        ? () => onConfirm?.call(batch, item)
                        : null,
                    onCorrect: item.pending
                        ? () => onCorrect?.call(batch, item)
                        : null,
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class AiDiaryItemCard extends StatelessWidget {
  const AiDiaryItemCard({
    required this.item,
    this.onConfirm,
    this.onCorrect,
    super.key,
  });

  final AiDiaryItem item;
  final VoidCallback? onConfirm;
  final VoidCallback? onCorrect;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        color: const Color(0xFFF9FCFE),
        border: Border.all(color: LarkColors.line),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  item.id,
                  style: const TextStyle(
                    color: LarkColors.text,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
              Text(
                item.statusLabel,
                style: TextStyle(
                  color: item.pending
                      ? const Color(0xFF9A6821)
                      : LarkColors.sky,
                  fontSize: 11,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            item.description,
            style: const TextStyle(color: LarkColors.text, height: 1.5),
          ),
          if (item.topics.isNotEmpty) ...[
            const SizedBox(height: 9),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: item.topics
                  .map((topic) => _TopicChip(label: topic))
                  .toList(),
            ),
          ],
          if (item.pending) ...[
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: onCorrect,
                    child: const Text('修改'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: FilledButton(
                    onPressed: onConfirm,
                    style: FilledButton.styleFrom(
                      backgroundColor: LarkColors.sky,
                    ),
                    child: const Text('确认'),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class MiniCalendar extends StatefulWidget {
  const MiniCalendar({
    required this.dates,
    required this.selectedDate,
    this.onDateSelected,
    super.key,
  });

  final List<String> dates;
  final String selectedDate;
  final ValueChanged<String>? onDateSelected;

  @override
  State<MiniCalendar> createState() => _MiniCalendarState();
}

class _MiniCalendarState extends State<MiniCalendar> {
  late DateTime _visibleMonth;

  @override
  void initState() {
    super.initState();
    final selected = _parseDate(widget.selectedDate) ?? DateTime.now();
    _visibleMonth = DateTime(selected.year, selected.month);
  }

  @override
  void didUpdateWidget(covariant MiniCalendar oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.selectedDate != widget.selectedDate) {
      final selected = _parseDate(widget.selectedDate) ?? DateTime.now();
      _visibleMonth = DateTime(selected.year, selected.month);
    }
  }

  void _moveMonth(int delta) {
    setState(() {
      _visibleMonth = DateTime(_visibleMonth.year, _visibleMonth.month + delta);
    });
  }

  @override
  Widget build(BuildContext context) {
    const days = ['一', '二', '三', '四', '五', '六', '日'];
    final markedDates = widget.dates.toSet();
    final firstDay = DateTime(_visibleMonth.year, _visibleMonth.month, 1);
    final leading = firstDay.weekday - 1;
    final total = DateTime(_visibleMonth.year, _visibleMonth.month + 1, 0).day;

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 14, 16, 0),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: LarkColors.line),
      ),
      child: Column(
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              IconButton(
                tooltip: '上个月',
                onPressed: () => _moveMonth(-1),
                icon: const Icon(Icons.chevron_left_rounded),
                color: LarkColors.subtle,
              ),
              Text(
                '${_visibleMonth.year}-${_visibleMonth.month.toString().padLeft(2, '0')}',
                style: const TextStyle(
                  fontWeight: FontWeight.w900,
                  color: LarkColors.text,
                ),
              ),
              IconButton(
                tooltip: '下个月',
                onPressed: () => _moveMonth(1),
                icon: const Icon(Icons.chevron_right_rounded),
                color: LarkColors.subtle,
              ),
            ],
          ),
          const SizedBox(height: 10),
          GridView.count(
            crossAxisCount: 7,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            childAspectRatio: 1.2,
            children: [
              ...days.map(
                (day) => Center(
                  child: Text(
                    day,
                    style: const TextStyle(
                      color: LarkColors.subtle,
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ),
              ...List.generate(leading, (_) => const SizedBox()),
              ...List.generate(total, (index) {
                final day = index + 1;
                final date = _dateKey(
                  DateTime(_visibleMonth.year, _visibleMonth.month, day),
                );
                final isSelected = date == widget.selectedDate;
                final marked = markedDates.contains(date);
                return Center(
                  child: InkWell(
                    customBorder: const CircleBorder(),
                    onTap: () => widget.onDateSelected?.call(date),
                    child: SizedBox(
                      width: 36,
                      height: 36,
                      child: Stack(
                        alignment: Alignment.center,
                        children: [
                          Container(
                            width: 30,
                            height: 30,
                            alignment: Alignment.center,
                            decoration: BoxDecoration(
                              color: isSelected
                                  ? LarkColors.sky
                                  : Colors.transparent,
                              shape: BoxShape.circle,
                            ),
                            child: Text(
                              '$day',
                              style: TextStyle(
                                color: isSelected
                                    ? Colors.white
                                    : LarkColors.text,
                                fontWeight: isSelected
                                    ? FontWeight.w800
                                    : FontWeight.w500,
                              ),
                            ),
                          ),
                          if (marked)
                            Positioned(
                              bottom: 3,
                              child: Container(
                                width: 4,
                                height: 4,
                                decoration: BoxDecoration(
                                  color: isSelected
                                      ? Colors.white
                                      : LarkColors.sky,
                                  shape: BoxShape.circle,
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                );
              }),
            ],
          ),
        ],
      ),
    );
  }
}

class DiaryCard extends StatelessWidget {
  const DiaryCard({
    required this.data,
    this.selected = false,
    this.onTap,
    this.onLongPress,
    super.key,
  });

  final DiaryCardData data;
  final bool selected;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        onLongPress: onLongPress,
        borderRadius: BorderRadius.circular(16),
        child: Ink(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: data.placeholder ? LarkColors.softBlue : Colors.white,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: selected
                  ? LarkColors.sky
                  : data.placeholder
                  ? LarkColors.skyLight
                  : LarkColors.line,
              width: selected ? 1.4 : 1,
            ),
            boxShadow: const [
              BoxShadow(
                color: Color(0x0E78AEE8),
                blurRadius: 13,
                offset: Offset(0, 5),
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 9,
                      vertical: 4,
                    ),
                    decoration: BoxDecoration(
                      color: data.type == 'AI记'
                          ? LarkColors.skyLight
                          : LarkColors.mintLight,
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text(
                      data.type,
                      style: const TextStyle(
                        color: LarkColors.text,
                        fontSize: 12,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ),
                  const Spacer(),
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        data.dateLabel,
                        style: const TextStyle(
                          color: LarkColors.subtle,
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      if (onTap != null) ...[
                        const SizedBox(width: 6),
                        const Icon(
                          Icons.chevron_right_rounded,
                          size: 18,
                          color: LarkColors.muted,
                        ),
                      ],
                    ],
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Text(
                data.title,
                style: const TextStyle(
                  color: LarkColors.text,
                  fontWeight: FontWeight.w800,
                  fontSize: 15,
                ),
              ),
              const SizedBox(height: 7),
              Text(
                data.body,
                style: const TextStyle(
                  color: LarkColors.subtle,
                  height: 1.45,
                  fontSize: 13,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class DiaryEditorDialog extends StatefulWidget {
  const DiaryEditorDialog({
    required this.date,
    required this.initialText,
    super.key,
  });

  final String date;
  final String initialText;

  @override
  State<DiaryEditorDialog> createState() => _DiaryEditorDialogState();
}

class _DiaryEditorDialogState extends State<DiaryEditorDialog> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initialText);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('${widget.date} 日记'),
      content: SizedBox(
        width: 420,
        child: TextField(
          controller: _controller,
          autofocus: true,
          keyboardType: TextInputType.multiline,
          textInputAction: TextInputAction.newline,
          minLines: 8,
          maxLines: 12,
          decoration: InputDecoration(
            hintText: '写下今天发生的事，或此刻最想被云雀记住的想法。',
            filled: true,
            fillColor: LarkColors.background,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(16),
              borderSide: const BorderSide(color: LarkColors.line),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(16),
              borderSide: const BorderSide(color: LarkColors.line),
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(_controller.text),
          style: FilledButton.styleFrom(backgroundColor: LarkColors.sky),
          child: const Text('保存'),
        ),
      ],
    );
  }
}

class AiDiaryCorrectionSheet extends StatefulWidget {
  const AiDiaryCorrectionSheet({required this.item, super.key});

  final AiDiaryItem item;

  @override
  State<AiDiaryCorrectionSheet> createState() => _AiDiaryCorrectionSheetState();
}

class _AiDiaryCorrectionSheetState extends State<AiDiaryCorrectionSheet> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.item.description);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).viewInsets.bottom;
    return Padding(
      padding: EdgeInsets.only(bottom: bottom),
      child: Container(
        decoration: const BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
        ),
        padding: const EdgeInsets.fromLTRB(18, 14, 18, 18),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Center(
              child: Container(
                width: 38,
                height: 4,
                decoration: BoxDecoration(
                  color: LarkColors.line,
                  borderRadius: BorderRadius.circular(999),
                ),
              ),
            ),
            const SizedBox(height: 16),
            Text(
              '修改 ${widget.item.id}',
              style: const TextStyle(
                color: LarkColors.text,
                fontSize: 20,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _controller,
              autofocus: true,
              keyboardType: TextInputType.multiline,
              textInputAction: TextInputAction.newline,
              minLines: 6,
              maxLines: 10,
              decoration: InputDecoration(
                hintText: '请写下更准确的理解。',
                filled: true,
                fillColor: LarkColors.background,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(16),
                  borderSide: const BorderSide(color: LarkColors.line),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(16),
                  borderSide: const BorderSide(color: LarkColors.line),
                ),
              ),
            ),
            const SizedBox(height: 14),
            FilledButton(
              onPressed: () => Navigator.of(context).pop(_controller.text),
              style: FilledButton.styleFrom(
                backgroundColor: LarkColors.sky,
                minimumSize: const Size.fromHeight(50),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
              ),
              child: const Text(
                '提交修改',
                style: TextStyle(fontWeight: FontWeight.w800),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class EmotionPage extends StatelessWidget {
  const EmotionPage({required this.snapshot, super.key});

  final EmotionSnapshot snapshot;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: LarkColors.background,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(18, 18, 18, 24),
        children: [
          const Text(
            '情绪画像',
            style: TextStyle(
              fontSize: 24,
              fontWeight: FontWeight.w900,
              color: LarkColors.text,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            '从主聊天页向右滑动可回到聊天。',
            style: TextStyle(color: LarkColors.subtle),
          ),
          const SizedBox(height: 18),
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: LarkColors.line),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Image(
                      image: AssetImage(_assetLarkIcon),
                      width: 74,
                      height: 74,
                      fit: BoxFit.cover,
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            snapshot.label,
                            style: const TextStyle(
                              fontSize: 22,
                              fontWeight: FontWeight.w900,
                              color: LarkColors.text,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            snapshot.change,
                            style: const TextStyle(color: LarkColors.subtle),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 22),
                ScoreBar(
                  label: '效价 Valence',
                  value: snapshot.valence,
                  min: -1,
                  max: 1,
                ),
                const SizedBox(height: 16),
                ScoreBar(
                  label: '唤醒度 Arousal',
                  value: snapshot.arousal,
                  min: 0,
                  max: 1,
                ),
                const SizedBox(height: 16),
                ScoreBar(
                  label: '置信度 Confidence',
                  value: snapshot.confidence,
                  min: 0,
                  max: 1,
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          const EmotionHintCard(
            title: '回应倾向',
            body: '云雀会优先把情绪画像转换成语气、节奏和安抚方式，而不是把分数直接压到对话里。',
          ),
          const SizedBox(height: 12),
          const EmotionHintCard(
            title: '模态状态',
            body: '第一版移动端先使用文本。音频和视频入口会在后续阶段接入。',
          ),
        ],
      ),
    );
  }
}

class ScoreBar extends StatelessWidget {
  const ScoreBar({
    required this.label,
    required this.value,
    required this.min,
    required this.max,
    super.key,
  });

  final String label;
  final double value;
  final double min;
  final double max;

  @override
  Widget build(BuildContext context) {
    final normalized = ((value - min) / (max - min)).clamp(0.0, 1.0);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                label,
                style: const TextStyle(
                  color: LarkColors.text,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            Text(
              value.toStringAsFixed(2),
              style: const TextStyle(
                color: LarkColors.subtle,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(999),
          child: LinearProgressIndicator(
            value: normalized,
            minHeight: 10,
            backgroundColor: LarkColors.softBlue,
            valueColor: const AlwaysStoppedAnimation(LarkColors.sky),
          ),
        ),
      ],
    );
  }
}

class EmotionHintCard extends StatelessWidget {
  const EmotionHintCard({required this.title, required this.body, super.key});

  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: LarkColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              color: LarkColors.text,
              fontWeight: FontWeight.w800,
              fontSize: 16,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            body,
            style: const TextStyle(color: LarkColors.subtle, height: 1.45),
          ),
        ],
      ),
    );
  }
}

class LarkUser {
  const LarkUser({required this.id, required this.username});

  factory LarkUser.fromJson(Map<String, dynamic> json) {
    return LarkUser(
      id: json['id']?.toString() ?? '',
      username: json['username']?.toString() ?? '云雀用户',
    );
  }

  final String id;
  final String username;
}

class ChatMessage {
  const ChatMessage({
    required this.fromLark,
    required this.text,
    required this.time,
  });

  factory ChatMessage.fromHistory(Map<String, dynamic> json) {
    final role = json['role']?.toString() ?? '';
    return ChatMessage(
      fromLark: role != 'user',
      text: json['content']?.toString() ?? '',
      time: _timeFromIso(json['created_at']?.toString()),
    );
  }

  final bool fromLark;
  final String text;
  final String time;
}

class DiaryCardData {
  const DiaryCardData({
    required this.dateLabel,
    required this.type,
    required this.title,
    required this.body,
    this.placeholder = false,
  });

  final String dateLabel;
  final String type;
  final String title;
  final String body;
  final bool placeholder;
}

class EmotionSnapshot {
  const EmotionSnapshot({required this.textScore, required this.fusionScore});

  final double textScore;
  final double fusionScore;

  // Compatibility getters for the retired full-page emotion widget.
  String get label => '文本情绪';
  double get valence => textScore;
  double get arousal => fusionScore;
  double get confidence => fusionScore;
  String get change => 'SELF-MM 文本模态';
}

class V2MemoryItem {
  const V2MemoryItem({
    required this.id,
    required this.layer,
    required this.description,
    required this.topics,
    required this.scene,
    required this.importance,
    required this.confidence,
    required this.linkedMemoryIds,
    required this.isNew,
  });

  factory V2MemoryItem.fromJson(Map<String, dynamic> json) {
    return V2MemoryItem(
      id: json['id']?.toString() ?? '',
      layer: MemoryLayerX.fromApiName(json['layer']?.toString() ?? ''),
      description: json['description']?.toString() ?? '',
      topics: _stringList(json['topics']),
      scene: json['scene']?.toString() ?? '',
      importance: _asDouble(json['importance']),
      confidence: _asDouble(json['confidence']),
      linkedMemoryIds: _stringList(json['linked_memory_ids']),
      isNew: json['is_new'] == true,
    );
  }

  final String id;
  final MemoryLayer layer;
  final String description;
  final List<String> topics;
  final String scene;
  final double importance;
  final double confidence;
  final List<String> linkedMemoryIds;
  final bool isNew;
}

class AiDiaryBatch {
  const AiDiaryBatch({
    required this.batchId,
    required this.dateKey,
    required this.items,
    required this.pendingCount,
  });

  factory AiDiaryBatch.fromJson(Map<String, dynamic> json) {
    return AiDiaryBatch(
      batchId: json['batch_id']?.toString() ?? '',
      dateKey: json['date_key']?.toString() ?? '',
      items: (json['items'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(AiDiaryItem.fromJson)
          .toList(),
      pendingCount: _asInt(json['pending_count']),
    );
  }

  final String batchId;
  final String dateKey;
  final List<AiDiaryItem> items;
  final int pendingCount;
}

class AiDiaryItem {
  const AiDiaryItem({
    required this.id,
    required this.topics,
    required this.description,
    required this.importance,
    required this.confidence,
    required this.reviewStatus,
  });

  factory AiDiaryItem.fromJson(Map<String, dynamic> json) {
    return AiDiaryItem(
      id: json['id']?.toString() ?? '',
      topics: _stringList(json['topics']),
      description: json['description']?.toString() ?? '',
      importance: _asDouble(json['importance']),
      confidence: _asDouble(json['confidence']),
      reviewStatus: json['review_status']?.toString() ?? 'pending',
    );
  }

  final String id;
  final List<String> topics;
  final String description;
  final double importance;
  final double confidence;
  final String reviewStatus;

  bool get pending => reviewStatus == 'pending';

  String get statusLabel => switch (reviewStatus) {
    'confirmed' => '已确认',
    'revised' => '已修改',
    'deleted' => '已删除',
    _ => '待审查',
  };
}

class AuthException implements Exception {
  const AuthException(this.message);
  final String message;

  @override
  String toString() => message;
}

class ApiException implements Exception {
  const ApiException(this.message);
  final String message;

  @override
  String toString() => message;
}

class LarkColors {
  static const background = Color(0xFFF4FAFF);
  static const softBlue = Color(0xFFEAF6FF);
  static const skyLight = Color(0xFFDDF1FF);
  static const sky = Color(0xFF79BCEB);
  static const mintLight = Color(0xFFE8F8F2);
  static const line = Color(0xFFDCECF7);
  static const text = Color(0xFF24445A);
  static const subtle = Color(0xFF6C8798);
  static const muted = Color(0xFF9AAEBA);
  static const online = Color(0xFF37C97A);
  static const offline = Color(0xFFFF6B6B);
}

extension MemoryLayerX on MemoryLayer {
  String get apiName => switch (this) {
    MemoryLayer.observation => 'observation',
    MemoryLayer.reflection => 'reflection',
    MemoryLayer.strategy => 'strategy',
  };

  String get label => switch (this) {
    MemoryLayer.observation => '观察',
    MemoryLayer.reflection => '反思',
    MemoryLayer.strategy => '策略',
  };

  IconData get icon => switch (this) {
    MemoryLayer.observation => Icons.visibility_outlined,
    MemoryLayer.reflection => Icons.psychology_outlined,
    MemoryLayer.strategy => Icons.route_outlined,
  };

  static MemoryLayer fromApiName(String value) {
    return switch (value) {
      'reflection' => MemoryLayer.reflection,
      'strategy' => MemoryLayer.strategy,
      _ => MemoryLayer.observation,
    };
  }
}

List<DiaryCardData> _buildDiaryCards(Map<String, dynamic> selected) {
  final date = selected['date']?.toString() ?? _dateKey(DateTime.now());
  final markdown = _nonEmpty(selected['user_markdown']);
  return [
    DiaryCardData(
      dateLabel: date,
      type: '日记',
      title: _isToday(date) ? '今天的用户记' : '$date 的用户记',
      body: markdown ?? '今天还没有写用户记。',
      placeholder: markdown == null,
    ),
  ];
}

bool _hasUserDiaryEntry(Map<String, dynamic> selected) {
  return _nonEmpty(selected['user_markdown']) != null;
}

List<String> _normalizeDiaryDates(
  Object? rawDates,
  Map<String, dynamic> selected,
) {
  final today = _dateKey(DateTime.now());
  final selectedDate = selected['date']?.toString();
  final dates = <String>{
    today,
    if (selectedDate != null && selectedDate.isNotEmpty) selectedDate,
  };
  if (rawDates is List) {
    for (final item in rawDates) {
      final date = item?.toString();
      if (date != null && RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(date)) {
        dates.add(date);
      }
    }
  }
  return _sortDiaryDates(dates);
}

List<String> _mergeDiaryDates(List<String> existing, List<String> incoming) {
  return _sortDiaryDates({...existing, ...incoming});
}

String _resolveSelectedDate({
  required String preferred,
  required List<String> availableDates,
}) {
  if (preferred.isNotEmpty) return preferred;
  if (availableDates.isNotEmpty) return availableDates.first;
  return _dateKey(DateTime.now());
}

List<String> _sortDiaryDates(Iterable<String> dates) {
  final sorted = dates.toList()..sort((a, b) => b.compareTo(a));
  return sorted;
}

List<DiaryCardData> _sortDiaryCards(Iterable<DiaryCardData> cards) {
  final sorted = cards.toList()
    ..sort((a, b) => b.dateLabel.compareTo(a.dateLabel));
  return sorted;
}

List<DiaryCardData> _fallbackDiaryCards() {
  final today = _dateKey(DateTime.now());
  return [
    DiaryCardData(
      dateLabel: today,
      type: '日记',
      title: '今天的用户记',
      body: '暂时无法连接服务，登录后会加载你的日记。',
      placeholder: true,
    ),
  ];
}

Map<String, dynamic> _decodeMap(String body) {
  if (body.isEmpty) return {};
  try {
    final decoded = jsonDecode(body);
    return decoded is Map<String, dynamic> ? decoded : {};
  } on FormatException {
    return {'error': _shortBody(body)};
  }
}

String _shortBody(String body) {
  final compact = body.replaceAll(RegExp(r'\s+'), ' ').trim();
  if (compact.length <= 180) return compact;
  return '${compact.substring(0, 180)}...';
}

String _responseError(http.Response response) {
  final json = _decodeMap(response.body);
  final error = _nonEmpty(json['error']);
  if (response.statusCode == 502) {
    return 'HTTP 502：云雀后端 api.lark.irises.me 当前不可用。';
  }
  if (error != null) {
    return 'HTTP ${response.statusCode}：$error';
  }
  return 'HTTP ${response.statusCode}';
}

String? _extractSessionCookie(String? setCookie) {
  if (setCookie == null || setCookie.isEmpty) return null;
  final match = RegExp(r'yunque_session=[^;,]+').firstMatch(setCookie);
  return match?.group(0);
}

String _authMessage(Map<String, dynamic> json, {int? statusCode}) {
  final error = json['error']?.toString();
  return switch (error) {
    'invalid_username' => '用户名格式不正确。',
    'invalid_password' => '密码至少需要 8 位。',
    'username_taken' => '这个用户名已经被注册。',
    'invalid_credentials' => '用户名或密码不对。',
    'unauthorized' => '登录会话无效，请重新登录。',
    _ =>
      statusCode == null
          ? '登录失败，请检查用户名和密码。'
          : '登录失败，HTTP $statusCode：${error ?? '未知错误'}',
  };
}

String? _nonEmpty(Object? value) {
  final text = value?.toString().trim();
  return text == null || text.isEmpty ? null : text;
}

double _asDouble(Object? value) {
  if (value is num) return value.toDouble();
  if (value is String) return double.tryParse(value) ?? 0;
  return 0;
}

int _asInt(Object? value) {
  if (value is num) return value.toInt();
  if (value is String) return int.tryParse(value) ?? 0;
  return 0;
}

List<String> _stringList(Object? value) {
  if (value is! List) return const [];
  return value
      .map((item) => item?.toString().trim() ?? '')
      .where((item) => item.isNotEmpty)
      .toList();
}

String _topicLabel(String topic) {
  return switch (topic) {
    'event' => '事件',
    'preference' => '偏好',
    'routine' => '习惯',
    'relationship' => '关系',
    _ => topic,
  };
}

String _dateKey(DateTime date) {
  return '${date.year.toString().padLeft(4, '0')}-'
      '${date.month.toString().padLeft(2, '0')}-'
      '${date.day.toString().padLeft(2, '0')}';
}

DateTime? _parseDate(String value) {
  final parts = value.split('-');
  if (parts.length != 3) return null;
  final year = int.tryParse(parts[0]);
  final month = int.tryParse(parts[1]);
  final day = int.tryParse(parts[2]);
  if (year == null || month == null || day == null) return null;
  return DateTime(year, month, day);
}

bool _isToday(String date) => date == _dateKey(DateTime.now());

String _shortTime(DateTime date) {
  return '${date.hour.toString().padLeft(2, '0')}:'
      '${date.minute.toString().padLeft(2, '0')}';
}

String _timeFromIso(String? value) {
  if (value == null) return '';
  final parsed = DateTime.tryParse(value);
  return parsed == null ? value : _shortTime(parsed.toLocal());
}
