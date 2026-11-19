import 'package:flutter/material.dart';

typedef ProfileJsonRequest = Future<Map<String, dynamic>> Function(
  String path, {
  String method,
  Map<String, dynamic>? body,
});

class ProfilePage extends StatefulWidget {
  const ProfilePage({
    super.key,
    required this.requestJson,
    this.onProfileSwitched,
  });

  final ProfileJsonRequest requestJson;
  final VoidCallback? onProfileSwitched;

  @override
  State<ProfilePage> createState() => _ProfilePageState();
}

class _ProfilePageState extends State<ProfilePage> {
  bool _loading = true;
  String? _error;
  List<Map<String, dynamic>> _profiles = [];
  String _activeId = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final res = await widget.requestJson('/api/profiles');
      final list = ((res['profiles'] as List?) ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      final active = (res['active_profile'] as Map?)?['id']?.toString() ?? '';
      if (!mounted) return;
      setState(() {
        _profiles = list;
        _activeId = active;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '加载用户画像失败：$e';
      });
    }
  }

  Future<void> _switchProfile(String profileId) async {
    try {
      await widget.requestJson(
        '/api/profiles/switch',
        method: 'POST',
        body: {'profile_id': profileId},
      );
      await _load();
      widget.onProfileSwitched?.call();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('已切换当前学习档案')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('切换失败：$e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(_error!, style: const TextStyle(color: Colors.red)),
            const SizedBox(height: 10),
            FilledButton(onPressed: _load, child: const Text('重试')),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text(
            '学习角色档案',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 6),
          const Text(
            '不同档案会为云雀提供对应的年级、学习阶段与目标背景。',
            style: TextStyle(fontSize: 12.5, color: Color(0xFF64748B)),
          ),
          const SizedBox(height: 12),
          if (_profiles.isEmpty)
            const Card(
              child: Padding(
                padding: EdgeInsets.all(16),
                child: Text('暂无档案，可在网页端或后续版本中创建。'),
              ),
            ),
          ..._profiles.map((p) {
            final id = (p['id'] ?? '').toString();
            final isActive = id == _activeId;
            final name = (p['name'] ?? '默认档案').toString();
            final stage = (p['stage'] ?? p['grade'] ?? '').toString();
            final goal = (p['target_goal'] ?? p['goal'] ?? '').toString();
            return Card(
              margin: const EdgeInsets.only(bottom: 10),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14),
                side: BorderSide(
                  color: isActive
                      ? const Color(0xFF2F6DB2)
                      : const Color(0xFFE2E8F0),
                ),
              ),
              child: ListTile(
                leading: CircleAvatar(
                  backgroundColor: isActive
                      ? const Color(0xFF2F6DB2)
                      : const Color(0xFFEAF3FD),
                  foregroundColor:
                      isActive ? Colors.white : const Color(0xFF2F6DB2),
                  child: const Icon(Icons.person_outline_rounded),
                ),
                title: Text(
                  name,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                subtitle: Text(
                  [if (stage.isNotEmpty) stage, if (goal.isNotEmpty) goal]
                      .join(' · '),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
                trailing: isActive
                    ? const Chip(label: Text('当前使用'))
                    : TextButton(
                        onPressed: () => _switchProfile(id),
                        child: const Text('切换'),
                      ),
              ),
            );
          }),
        ],
      ),
    );
  }
}
