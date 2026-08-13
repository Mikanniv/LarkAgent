import 'package:http/http.dart' as http;

import 'lark_http_client_io.dart'
    if (dart.library.js_interop) 'lark_http_client_web.dart';

http.Client createLarkHttpClient() => createPlatformClient();
