import 'dart:io';

Future<List<int>> readVoiceFile(String path) => File(path).readAsBytes();

Future<void> deleteVoiceFile(String path) async {
  final file = File(path);
  if (await file.exists()) await file.delete();
}
