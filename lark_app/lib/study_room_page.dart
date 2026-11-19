import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

typedef StudyJsonRequest = Future<Map<String, dynamic>> Function(
  String path, {
  String method,
  Map<String, dynamic>? body,
});

class StudyRoomPage extends StatefulWidget {
  const StudyRoomPage({
    super.key,
    required this.requestJson,
  });

  final StudyJsonRequest requestJson;

  @override
  State<StudyRoomPage> createState() => _StudyRoomPageState();
}

class _StudyRoomPageState extends State<StudyRoomPage> {
  final TextEditingController _inputCtrl = TextEditingController();
  final ScrollController _scrollCtrl = ScrollController();

  bool _loadingSessions = true;
  bool _loadingMessages = false;
  bool _sending = false;
  String? _error;

  List<Map<String, dynamic>> _sessions = [];
  String? _activeSessionId;
  List<Map<String, dynamic>> _messages = [];
  List<Map<String, dynamic>> _libraryFiles = [];

  @override
  void initState() {
    super.initState();
    _loadSessions();
  }

  @override
  void dispose() {
    _inputCtrl.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  Map<String, dynamic>? get _activeSession {
    for (final s in _sessions) {
      if (s['id']?.toString() == _activeSessionId) return s;
    }
    return _sessions.isNotEmpty ? _sessions.first : null;
  }

  int get _linkedCount =>
      _libraryFiles.where((f) => f['linked'] == true).length;

  Future<void> _loadSessions() async {
    setState(() {
      _loadingSessions = true;
      _error = null;
    });
    try {
      final res = await widget.requestJson('/api/study/sessions');
      final list = ((res['sessions'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      if (!mounted) return;
      setState(() {
        _sessions = list;
        _loadingSessions = false;
        if (list.isNotEmpty) {
          final stillExists = list.any((s) => s['id'] == _activeSessionId);
          _activeSessionId = stillExists
              ? _activeSessionId
              : list.first['id']?.toString();
        } else {
          _activeSessionId = null;
          _messages = [];
        }
      });
      if (_activeSessionId != null) {
        await Future.wait([
          _loadMessages(_activeSessionId!),
          _loadLibrary(_activeSessionId!),
        ]);
      } else {
        await _loadLibrary('');
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadingSessions = false;
        _error = '加载自习室失败：$e';
      });
    }
  }

  Future<void> _loadMessages(String sessionId) async {
    setState(() => _loadingMessages = true);
    try {
      final res = await widget.requestJson(
        '/api/study/messages?session_id=${Uri.encodeQueryComponent(sessionId)}',
      );
      final list = ((res['messages'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      if (!mounted) return;
      setState(() {
        _messages = list;
        _loadingMessages = false;
      });
      _scrollToBottom();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadingMessages = false;
        _error = '加载消息失败：$e';
      });
    }
  }

  Future<void> _loadLibrary(String sessionId) async {
    try {
      final q = sessionId.isNotEmpty
          ? '?session_id=${Uri.encodeQueryComponent(sessionId)}'
          : '';
      final res = await widget.requestJson('/api/study/library$q');
      final list = ((res['files'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      if (!mounted) return;
      setState(() => _libraryFiles = list);
    } catch (_) {}
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollCtrl.hasClients) return;
      _scrollCtrl.animateTo(
        _scrollCtrl.position.maxScrollExtent + 120,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOut,
      );
    });
  }

  Future<void> _createSessionDialog() async {
    final subjectCtrl = TextEditingController();
    final titleCtrl = TextEditingController();
    final seedCtrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('新建自习室'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: subjectCtrl,
              decoration: const InputDecoration(
                labelText: '学科 / 科目 *',
                hintText: '如：操作系统、高等数学、英语',
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: titleCtrl,
              decoration: const InputDecoration(
                labelText: '自习主题',
                hintText: '如：第三章 内存管理复习',
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: seedCtrl,
              decoration: const InputDecoration(
                labelText: '初始要求（可选）',
                hintText: '如：重点帮我梳理易错题',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('开启'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    final subject = subjectCtrl.text.trim();
    if (subject.isEmpty) return;
    final title = titleCtrl.text.trim().isEmpty
        ? '$subject 重点自习'
        : titleCtrl.text.trim();
    try {
      final res = await widget.requestJson(
        '/api/study/sessions',
        method: 'POST',
        body: {
          'subject': subject,
          'title': title,
          'prompt_seed': seedCtrl.text.trim(),
        },
      );
      final sess = res['session'] as Map?;
      if (sess != null) {
        _activeSessionId = sess['id']?.toString();
      }
      await _loadSessions();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('创建失败：$e')),
        );
      }
    }
  }

  Future<void> _sendQuestion(String rawText, {String pinnedChunkId = ''}) async {
    final text = rawText.trim();
    final sessionId = _activeSessionId;
    if (text.isEmpty || sessionId == null || _sending) return;

    _inputCtrl.clear();
    setState(() {
      _sending = true;
      _messages = [
        ..._messages,
        {'role': 'user', 'content': text, 'meta': <String, dynamic>{}},
      ];
    });
    _scrollToBottom();

    try {
      final res = await widget.requestJson(
        '/api/study/chat',
        method: 'POST',
        body: {
          'session_id': sessionId,
          'content': text,
          if (pinnedChunkId.isNotEmpty) 'pinned_chunk_id': pinnedChunkId,
        },
      );
      if (!mounted) return;
      final reply = (res['reply'] ?? '').toString();
      final ragMeta = (res['rag_meta'] is Map)
          ? Map<String, dynamic>.from(res['rag_meta'] as Map)
          : <String, dynamic>{};
      final libFiles = ((res['library_files'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      setState(() {
        _sending = false;
        _messages = [
          ..._messages,
          {'role': 'assistant', 'content': reply, 'meta': ragMeta},
        ];
        if (libFiles.isNotEmpty) _libraryFiles = libFiles;
      });
      _scrollToBottom();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _sending = false;
        _messages = [
          ..._messages,
          {
            'role': 'assistant',
            'content': '回答失败：$e',
            'meta': <String, dynamic>{},
          },
        ];
      });
    }
  }

  Future<void> _uploadLibraryFile(StateSetter? modalSetState) async {
    final picked = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: const [
        'pdf', 'pptx', 'docx', 'xlsx', 'csv', 'txt', 'md', 'json',
        'py', 'js', 'ts', 'java', 'c', 'cpp', 'html', 'css',
      ],
    );
    if (picked.isEmpty) return;
    final attachments = <Map<String, dynamic>>[];
    for (final f in picked.take(5)) {
      final bytes = await f.readAsBytes();
      if (bytes.isEmpty) continue;
      if (bytes.length > 10 * 1024 * 1024) continue;
      final b64 = base64Encode(bytes);
      attachments.add({
        'name': f.name,
        'type': 'application/octet-stream',
        'size': bytes.length,
        'data': 'data:application/octet-stream;base64,$b64',
      });
    }
    if (attachments.isEmpty) return;
    try {
      final res = await widget.requestJson(
        '/api/study/library',
        method: 'POST',
        body: {
          'session_id': _activeSessionId ?? '',
          'attachments': attachments,
        },
      );
      final list = ((res['files'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      if (mounted) {
        setState(() => _libraryFiles = list);
        modalSetState?.call(() {});
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('已入库并切片 ${attachments.length} 份学习资料')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('上传失败：$e')),
        );
      }
    }
  }

  Future<void> _toggleFileLink(
    String fileId,
    bool linked,
    StateSetter modalSetState,
  ) async {
    if (_activeSessionId == null) return;
    try {
      final res = await widget.requestJson(
        '/api/study/session/links',
        method: 'POST',
        body: {
          'session_id': _activeSessionId,
          'file_id': fileId,
          'linked': linked,
        },
      );
      final list = ((res['files'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      if (mounted) {
        setState(() => _libraryFiles = list);
        modalSetState(() {});
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('更新关联失败：$e')),
        );
      }
    }
  }

  Future<void> _deleteLibraryFile(
    String fileId,
    StateSetter modalSetState,
  ) async {
    try {
      final res = await widget.requestJson(
        '/api/study/library/delete',
        method: 'POST',
        body: {
          'session_id': _activeSessionId ?? '',
          'file_id': fileId,
        },
      );
      final list = ((res['files'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      if (mounted) {
        setState(() => _libraryFiles = list);
        modalSetState(() {});
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('删除失败：$e')),
        );
      }
    }
  }

  Future<void> _showLibrarySheet() async {
    await _loadLibrary(_activeSessionId ?? '');
    if (!mounted) return;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, modalSetState) => DraggableScrollableSheet(
          expand: false,
          initialChildSize: 0.72,
          maxChildSize: 0.92,
          builder: (_, scrollController) => Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            '学习资料库',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          Text(
                            '本自习室已关联 $_linkedCount / ${_libraryFiles.length} 份（仅检索已勾选资料）',
                            style: const TextStyle(
                              fontSize: 12,
                              color: Color(0xFF64748B),
                            ),
                          ),
                        ],
                      ),
                    ),
                    FilledButton.icon(
                      onPressed: () => _uploadLibraryFile(modalSetState),
                      icon: const Icon(Icons.upload_file_rounded, size: 17),
                      label: const Text('上传'),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Expanded(
                  child: _libraryFiles.isEmpty
                      ? const Center(
                          child: Text(
                            '暂无学习资料，点击右上角上传 PDF / PPTX / Word / Markdown / 代码',
                            textAlign: TextAlign.center,
                            style: TextStyle(color: Color(0xFF64748B)),
                          ),
                        )
                      : ListView.separated(
                          controller: scrollController,
                          itemCount: _libraryFiles.length,
                          separatorBuilder: (_, _) => const SizedBox(height: 8),
                          itemBuilder: (_, idx) {
                            final f = _libraryFiles[idx];
                            final linked = f['linked'] == true;
                            final topics = ((f['topics'] as List?) ?? [])
                                .map((e) => e.toString())
                                .take(5)
                                .toList();
                            final ft = (f['file_type'] ?? 'FILE')
                                .toString()
                                .toUpperCase();
                            return Container(
                              padding: const EdgeInsets.all(10),
                              decoration: BoxDecoration(
                                color: linked
                                    ? const Color(0xFFEFF6FF)
                                    : const Color(0xFFF8FAFC),
                                borderRadius: BorderRadius.circular(12),
                                border: Border.all(
                                  color: linked
                                      ? const Color(0xFF93C5FD)
                                      : const Color(0xFFE2E8F0),
                                ),
                              ),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    children: [
                                      Checkbox(
                                        value: linked,
                                        onChanged: _activeSessionId == null
                                            ? null
                                            : (v) => _toggleFileLink(
                                                  f['id'].toString(),
                                                  v == true,
                                                  modalSetState,
                                                ),
                                      ),
                                      Container(
                                        padding: const EdgeInsets.symmetric(
                                          horizontal: 6,
                                          vertical: 2,
                                        ),
                                        decoration: BoxDecoration(
                                          color: const Color(0xFFDBEAFE),
                                          borderRadius:
                                              BorderRadius.circular(6),
                                        ),
                                        child: Text(
                                          ft,
                                          style: const TextStyle(
                                            fontSize: 10,
                                            fontWeight: FontWeight.w700,
                                            color: Color(0xFF1D4ED8),
                                          ),
                                        ),
                                      ),
                                      const SizedBox(width: 6),
                                      Expanded(
                                        child: Text(
                                          (f['file_name'] ?? '').toString(),
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                          style: const TextStyle(
                                            fontWeight: FontWeight.w600,
                                            fontSize: 13.5,
                                          ),
                                        ),
                                      ),
                                      IconButton(
                                        icon: const Icon(
                                          Icons.delete_outline_rounded,
                                          size: 18,
                                          color: Color(0xFFDC2626),
                                        ),
                                        onPressed: () => _deleteLibraryFile(
                                          f['id'].toString(),
                                          modalSetState,
                                        ),
                                      ),
                                    ],
                                  ),
                                  Padding(
                                    padding: const EdgeInsets.only(left: 12),
                                    child: Text(
                                      '${f['chunk_count'] ?? 0} 个切片',
                                      style: const TextStyle(
                                        fontSize: 11.5,
                                        color: Color(0xFF64748B),
                                      ),
                                    ),
                                  ),
                                  if (topics.isNotEmpty) ...[
                                    const SizedBox(height: 6),
                                    Padding(
                                      padding: const EdgeInsets.only(left: 12),
                                      child: Wrap(
                                        spacing: 6,
                                        runSpacing: 4,
                                        children: topics
                                            .map((t) => _TopicPill(text: t))
                                            .toList(),
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                            );
                          },
                        ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _showChunkDialog(Map<String, dynamic> chunk) {
    final docName = (chunk['doc_name'] ?? chunk['file_name'] ?? '资料').toString();
    final loc = (chunk['location'] ?? '').toString();
    final title = (chunk['section_title'] ?? '').toString();
    final topics = ((chunk['topics'] as List?) ?? []).map((e) => e.toString()).toList();
    final content = (chunk['content'] ?? chunk['snippet'] ?? '').toString();

    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('$docName · $loc', style: const TextStyle(fontSize: 15)),
        content: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              if (title.isNotEmpty) ...[
                Text(
                  title,
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                    color: Color(0xFF334155),
                  ),
                ),
                const SizedBox(height: 8),
              ],
              if (topics.isNotEmpty) ...[
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: topics.map((t) => _TopicPill(text: t)).toList(),
                ),
                const SizedBox(height: 10),
              ],
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xFFF8FAFC),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  content,
                  style: const TextStyle(fontSize: 13, height: 1.55),
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('关闭'),
          ),
          FilledButton(
            onPressed: () {
              Navigator.pop(ctx);
              _askAboutChunk(chunk);
            },
            child: const Text('学习此主题'),
          ),
        ],
      ),
    );
  }

  void _askAboutChunk(Map<String, dynamic> chunk) {
    final docName = (chunk['doc_name'] ?? '学习资料').toString();
    final loc = (chunk['location'] ?? '').toString();
    final title = (chunk['section_title'] ?? '').toString();
    final topics = ((chunk['topics'] as List?) ?? []).map((e) => e.toString()).take(4).toList();
    final topicPart = topics.isNotEmpty ? '（主题词：${topics.join('、')}）' : '';
    final prompt = '请结合《$docName》$loc${title.isNotEmpty ? '「$title」' : ''}$topicPart，详细讲解这一部分的核心知识点。';
    _sendQuestion(prompt, pinnedChunkId: (chunk['chunk_id'] ?? chunk['id'] ?? '').toString());
  }

  @override
  Widget build(BuildContext context) {
    if (_loadingSessions) {
      return const Center(child: CircularProgressIndicator());
    }
    final active = _activeSession;

    return Column(
      children: [
        // Top study session bar + Material library button
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: const BoxDecoration(
            color: Colors.white,
            border: Border(bottom: BorderSide(color: Color(0xFFE6EEF7))),
          ),
          child: Row(
            children: [
              Expanded(
                child: _sessions.isEmpty
                    ? const Text(
                        '还没有自习室会话，点右侧新建一个吧',
                        style: TextStyle(fontSize: 13, color: Color(0xFF64748B)),
                      )
                    : DropdownButtonHideUnderline(
                        child: DropdownButton<String>(
                          isExpanded: true,
                          value: active?['id']?.toString(),
                          items: _sessions
                              .map(
                                (s) => DropdownMenuItem<String>(
                                  value: s['id']?.toString(),
                                  child: Text(
                                    '${s['subject'] ?? '自习'} · ${s['title'] ?? ''}',
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                      fontSize: 13.5,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ),
                              )
                              .toList(),
                          onChanged: (id) {
                            if (id == null) return;
                            setState(() => _activeSessionId = id);
                            _loadMessages(id);
                            _loadLibrary(id);
                          },
                        ),
                      ),
              ),
              const SizedBox(width: 6),
              OutlinedButton.icon(
                onPressed: _showLibrarySheet,
                icon: const Icon(Icons.folder_copy_outlined, size: 16),
                label: Text('资料库 $_linkedCount'),
                style: OutlinedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  textStyle: const TextStyle(fontSize: 12),
                ),
              ),
              const SizedBox(width: 6),
              IconButton(
                onPressed: _createSessionDialog,
                tooltip: '新建自习室',
                icon: const Icon(Icons.add_circle_outline_rounded),
              ),
            ],
          ),
        ),

        if (_error != null)
          Padding(
            padding: const EdgeInsets.all(10),
            child: Text(_error!, style: const TextStyle(color: Colors.red)),
          ),

        // Chat list
        Expanded(
          child: _loadingMessages
              ? const Center(child: CircularProgressIndicator())
              : _messages.isEmpty
                  ? Center(
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Text(
                          _sessions.isEmpty
                              ? '点击右上角 + 创建你的第一个自习室，关联学习资料后即可开始溯源问答与继续学习。'
                              : '自习室已开启！先点右上角「资料库」勾选关联资料，再向云雀提问吧。',
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            color: Color(0xFF64748B),
                            height: 1.5,
                          ),
                        ),
                      ),
                    )
                  : ListView.builder(
                      controller: _scrollCtrl,
                      padding: const EdgeInsets.fromLTRB(12, 12, 12, 16),
                      itemCount: _messages.length + (_sending ? 1 : 0),
                      itemBuilder: (_, idx) {
                        if (idx >= _messages.length) {
                          return const Padding(
                            padding: EdgeInsets.symmetric(vertical: 8),
                            child: Text(
                              '云雀正在检索关联资料并整理溯源解答……',
                              style: TextStyle(
                                color: Color(0xFF64748B),
                                fontSize: 13,
                              ),
                            ),
                          );
                        }
                        final msg = _messages[idx];
                        final isUser = msg['role'] == 'user';
                        final meta = (msg['meta'] is Map)
                            ? Map<String, dynamic>.from(msg['meta'] as Map)
                            : <String, dynamic>{};
                        return _StudyMessageCard(
                          isUser: isUser,
                          content: (msg['content'] ?? '').toString(),
                          ragMeta: meta,
                          onTapChunk: _showChunkDialog,
                          onLearnChunk: _askAboutChunk,
                        );
                      },
                    ),
        ),

        // Input composer
        SafeArea(
          top: false,
          child: Container(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 10),
            decoration: const BoxDecoration(
              color: Colors.white,
              border: Border(top: BorderSide(color: Color(0xFFE6EEF7))),
            ),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _inputCtrl,
                    minLines: 1,
                    maxLines: 4,
                    enabled: _activeSessionId != null && !_sending,
                    decoration: InputDecoration(
                      hintText: _activeSessionId == null
                          ? '请先新建自习室'
                          : '向云雀提问（严格基于已关联资料作答）…',
                      filled: true,
                      fillColor: const Color(0xFFF4F8FC),
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 10,
                      ),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(18),
                        borderSide: BorderSide.none,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton.filled(
                  onPressed: (_activeSessionId == null || _sending)
                      ? null
                      : () => _sendQuestion(_inputCtrl.text),
                  icon: const Icon(Icons.send_rounded, size: 18),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _StudyMessageCard extends StatelessWidget {
  const _StudyMessageCard({
    required this.isUser,
    required this.content,
    required this.ragMeta,
    required this.onTapChunk,
    required this.onLearnChunk,
  });

  final bool isUser;
  final String content;
  final Map<String, dynamic> ragMeta;
  final ValueChanged<Map<String, dynamic>> onTapChunk;
  final ValueChanged<Map<String, dynamic>> onLearnChunk;

  @override
  Widget build(BuildContext context) {
    final grounded = ragMeta['grounded'] == true;
    final abstained = ragMeta['abstained'] == true;
    final sources = ((ragMeta['sources'] as List?) ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    final recs = ((ragMeta['recommendations'] as List?) ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * (isUser ? 0.80 : 0.92),
        ),
        child: Column(
          crossAxisAlignment:
              isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
              decoration: BoxDecoration(
                color: isUser
                    ? const Color(0xFF2F6DB2)
                    : (abstained ? const Color(0xFFFFFBEB) : Colors.white),
                borderRadius: BorderRadius.circular(16),
                border: isUser
                    ? null
                    : Border.all(
                        color: abstained
                            ? const Color(0xFFF59E0B)
                            : const Color(0xFFE2EBF5),
                      ),
              ),
              child: SelectableText(
                content,
                style: TextStyle(
                  fontSize: 14,
                  height: 1.55,
                  color: isUser ? Colors.white : const Color(0xFF1E293B),
                ),
              ),
            ),
            if (!isUser && grounded) ...[
              const SizedBox(height: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                decoration: BoxDecoration(
                  color: abstained
                      ? const Color(0xFFFEF3C7)
                      : const Color(0xFFF1F5F9),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  '${abstained ? '诚实拒答 · 相关度不足' : '已溯源作答'}  ·  最高相关度 ${(ragMeta['max_score'] ?? 0).toString()}（阈值 ${(ragMeta['threshold'] ?? 0.22).toString()}）',
                  style: TextStyle(
                    fontSize: 11.5,
                    fontWeight: FontWeight.w600,
                    color: abstained
                        ? const Color(0xFFB45309)
                        : const Color(0xFF047857),
                  ),
                ),
              ),
              if (sources.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text(
                  abstained ? '最相关的候选切片（仅供参考）' : '引用来源（点击查看原切片）',
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: Color(0xFF475569),
                  ),
                ),
                const SizedBox(height: 4),
                ...sources.map((src) {
                  final topics = ((src['topics'] as List?) ?? [])
                      .map((e) => e.toString())
                      .take(4)
                      .toList();
                  return GestureDetector(
                    onTap: () => onTapChunk(src),
                    child: Container(
                      margin: const EdgeInsets.only(bottom: 6),
                      padding: const EdgeInsets.all(9),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: const Color(0xFFE2E8F0)),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '[${src['cite_id'] ?? 'S'}] ${src['doc_name'] ?? ''} · ${src['location'] ?? ''}',
                            style: const TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: Color(0xFF1E293B),
                            ),
                          ),
                          if (topics.isNotEmpty) ...[
                            const SizedBox(height: 4),
                            Wrap(
                              spacing: 4,
                              runSpacing: 4,
                              children: topics
                                  .map((t) => _TopicPill(text: t))
                                  .toList(),
                            ),
                          ],
                          if ((src['snippet'] ?? '').toString().isNotEmpty) ...[
                            const SizedBox(height: 4),
                            Text(
                              src['snippet'].toString(),
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 11.5,
                                color: Color(0xFF64748B),
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                  );
                }),
              ],
              if (!abstained && recs.isNotEmpty) ...[
                const SizedBox(height: 6),
                const Text(
                  '继续学习 · 按主题词选择下一个学习切片',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: Color(0xFF047857),
                  ),
                ),
                const SizedBox(height: 4),
                ...recs.map((rec) {
                  final topics = ((rec['topics'] as List?) ?? [])
                      .map((e) => e.toString())
                      .take(5)
                      .toList();
                  return Container(
                    margin: const EdgeInsets.only(bottom: 6),
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF0FDF9),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: const Color(0xFFA7F3D0)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: Text(
                                '${rec['doc_name'] ?? ''} · ${rec['location'] ?? ''}',
                                style: const TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                            Text(
                              (rec['reason'] ?? '推荐学习').toString(),
                              style: const TextStyle(
                                fontSize: 11,
                                color: Color(0xFF047857),
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ],
                        ),
                        if ((rec['section_title'] ?? '').toString().isNotEmpty) ...[
                          const SizedBox(height: 3),
                          Text(
                            rec['section_title'].toString(),
                            style: const TextStyle(
                              fontSize: 12,
                              color: Color(0xFF334155),
                            ),
                          ),
                        ],
                        if (topics.isNotEmpty) ...[
                          const SizedBox(height: 5),
                          Wrap(
                            spacing: 4,
                            runSpacing: 4,
                            children:
                                topics.map((t) => _TopicPill(text: t)).toList(),
                          ),
                        ],
                        const SizedBox(height: 6),
                        Row(
                          children: [
                            FilledButton(
                              onPressed: () => onLearnChunk(rec),
                              style: FilledButton.styleFrom(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 10,
                                  vertical: 4,
                                ),
                                minimumSize: Size.zero,
                                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                                textStyle: const TextStyle(fontSize: 11.5),
                              ),
                              child: const Text('学习此主题'),
                            ),
                            const SizedBox(width: 8),
                            OutlinedButton(
                              onPressed: () => onTapChunk(rec),
                              style: OutlinedButton.styleFrom(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 10,
                                  vertical: 4,
                                ),
                                minimumSize: Size.zero,
                                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                                textStyle: const TextStyle(fontSize: 11.5),
                              ),
                              child: const Text('查看切片'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  );
                }),
              ],
            ],
          ],
        ),
      ),
    );
  }
}

class _TopicPill extends StatelessWidget {
  const _TopicPill({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: const Color(0xFFE0EDFF),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        '# $text',
        style: const TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w500,
          color: Color(0xFF1D4ED8),
        ),
      ),
    );
  }
}
