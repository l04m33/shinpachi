(function ($) {
    var start_time;
    var log_target;
    var streams = {};
    var flows = {};
    var subscriptions = {};

    var http_req_re = new RegExp('^(OPTIONS|GET|HEAD|POST|PUT|DELETE|TRACE|CONNECT) +([^ ]+) +HTTP\/([0-9.]+)\r\n');
    var http_rep_re = new RegExp('^HTTP/([0-9.]+) +([0-9]+) +(.+)\r\n');
    var topic_re = new RegExp('^(([0-9]+(\\.[0-9]+){3})|\\[([:0-9a-fA-F]+)\\]):([0-9]+)-(([0-9]+(\\.[0-9]+){3})|\\[([:0-9a-fA-F]+)\\]):([0-9]+):\r\n');

    var endpoint4_re = new RegExp('^([0-9]{1,3}(\\.[0-9]{1,3}){3})(:[0-9]{1,5}){0,1}$');
    var endpoint6_ip_only_re = new RegExp('^([0-9a-fA-F]{0,4}(\\:[0-9a-fA-F]{1,4}){0,7})(\\:?)((\\:[0-9a-fA-F]{1,4}){1,7})$');
    var endpoint6_ip_port_re = new RegExp('^\\[([0-9a-fA-F]{0,4}(\\:[0-9a-fA-F]{1,4}){0,7})(\\:?)((\\:[0-9a-fA-F]{1,4}){1,7})\\]\\:([0-9]{1,5})$');

    var following_events = false;
    var auto_scrolling = false;
    var ws_conn;

    var content_type_to_hljs_lang = [
        {
            re:     '^text/html$',
            langs:  ['html', 'json', 'javascript']
        },
        {
            re:     '^text/css$',
            langs:  ['css']
        },
        {
            re:     '^application/x-www-form-urlencoded$',
            langs:  ['http']    // TODO
        },
        {
            re:     'javascript',
            langs:  ['javascript']
        },
        {
            re:     'json',
            langs:  ['json']
        },
        {
            re:     '^text/',
            langs:  hljs.listLanguages()
        }
    ];

    var get_langs_by_content_type = function (content_type) {
        for (var t = 0; t < content_type_to_hljs_lang.length; t++) {
            if (content_type.match(content_type_to_hljs_lang[t].re) !== null) {
                return content_type_to_hljs_lang[t].langs;
            }
        }
        return undefined;
    };

    var real_typeof = function (v) {
        if (typeof(v) == "object") {
            if (v === null) return "null";
            if (v.constructor == (new Array()).constructor) return "array";
            if (v.constructor == (new Date()).constructor) return "date";
            if (v.constructor == (new RegExp()).constructor) return "regex";
            return "object";
        }
        return typeof(v);
    };

    var format_json = function (oData, sIndent) {
        if (arguments.length < 2) {
            var sIndent = "";
        }
        var sIndentStyle = "    ";
        var sDataType = real_typeof(oData);

        // open object
        if (sDataType == "array") {
            if (oData.length == 0) {
                return "[]";
            }
            var sHTML = "[";
        } else {
            var iCount = 0;
            $.each(oData, function() {
                iCount++;
                return;
            });
            if (iCount == 0) { // object is empty
                return "{}";
            }
            var sHTML = "{";
        }

        // loop through items
        var iCount = 0;
        $.each(oData, function(sKey, vValue) {
            if (iCount > 0) {
                sHTML += ",";
            }
            if (sDataType == "array") {
                sHTML += ("\n" + sIndent + sIndentStyle);
            } else {
                sHTML += ("\n" + sIndent + sIndentStyle + "\"" + sKey + "\"" + ": ");
            }

            // display relevant data type
            switch (real_typeof(vValue)) {
                case "array":
                case "object":
                    sHTML += format_json(vValue, (sIndent + sIndentStyle));
                    break;
                case "boolean":
                case "number":
                    sHTML += vValue.toString();
                    break;
                case "null":
                    sHTML += "null";
                    break;
                case "string":
                    sHTML += ("\"" + vValue + "\"");
                    break;
                default:
                    sHTML += ("TYPEOF: " + typeof(vValue));
            }

            // loop
            iCount++;
        });

        // close object
        if (sDataType == "array") {
            sHTML += ("\n" + sIndent + "]");
        } else {
            sHTML += ("\n" + sIndent + "}");
        }

        // return
        return sHTML;
    };

    var binary_string_to_arraybuffer = function (str) {
        var arr = new Uint8Array(str.length);

        for (var i = 0; i < str.length; i++) {
            arr[i] = str.charCodeAt(i) & 0xff;
        }

        return arr.buffer;
    };

    var enclose_addr = function (addr) {
        if (addr.indexOf(':') >= 0) {
            return '[' + addr + ']';
        }
        return addr;
    };

    var set_text = function (elem, text) {
        elem.appendChild(document.createTextNode(text));
    };

    var parse_content_type = function(content_type) {
        var split_ct = content_type.split(';');
        var ct_val = split_ct[0];

        var params = {};
        var split_param;
        for (var i = 1; i < split_ct.length; i++) {
            split_param = split_ct[i].trim().split('=');
            params[split_param[0]] = split_param[1];
        }

        return {'content_type': ct_val, 'params': params};
    };

    var gen_detail_header = function (tag, header_text) {
        var header, span;

        header = document.createElement(tag);
        span = document.createElement('span');
        set_text(span, header_text);
        header.appendChild(span);

        return header;
    };

    var get_li_class_by_idx = function (li_idx) {
        if (li_idx % 2 === 0) {
            return 'odd';
        } else {
            return 'even';
        }
    };

    var gen_detail_li = function (label_text, content_text, idx) {
        var li = document.createElement('li');
        var label = document.createElement('span');
        var content = document.createElement('span');
        var new_div = document.createElement('div');

        li.className = get_li_class_by_idx(idx);

        new_div.className = 'line';

        label.className = 'label';
        content.className = 'content';

        set_text(label, label_text);
        set_text(content, content_text);

        new_div.appendChild(label);
        new_div.appendChild(content);
        li.appendChild(new_div);
        return li;
    };

    var gen_network_list = function (stream) {
        var ul, li;
        var addr;
        var li_idx = 0;

        ul = document.createElement('ul');

        addr = enclose_addr(stream['src_addr']) + ':' + stream['src_port'];
        li = gen_detail_li('Source', addr, li_idx++);
        ul.appendChild(li);

        addr = enclose_addr(stream['dst_addr']) + ':' + stream['dst_port'];
        li = gen_detail_li('Destination', addr, li_idx++);
        ul.appendChild(li);

        return ul;
    };

    var gen_raw_data_pre_code = function (content) {
        var hex_pre = document.createElement('pre');
        hex_pre.className = 'raw-data-hex';
        var hex_code = document.createElement('code');
        var hex_text = document.createTextNode('');

        var txt_pre = document.createElement('pre');
        txt_pre.className = 'raw-data-txt';
        var txt_code = document.createElement('code');
        var txt_text = document.createTextNode('');

        var rd = new FileReader();

        rd.addEventListener('loadend', function () {
            var data = new Uint8Array(rd.result);
            var hex, txt;
            var hex_buf = '';
            var txt_buf = '';
            for (var i = 0; i < data.length; i++) {
                hex = (data[i] + 0x100).toString(16).substr(-2).toUpperCase();
                if (data[i] >= 0x20 && data[i] <= 0x7e) {
                    // printable
                    txt = String.fromCharCode(data[i]);
                } else {
                    txt = '.';
                }
                if ((i + 1) % 16 === 0) {
                    hex += '\n';
                    txt += '\n';
                } else {
                    if ((i + 1) % 8 === 0) {
                        hex += '  ';
                    } else {
                        hex += ' ';
                    }
                }
                hex_buf += hex;
                txt_buf += txt;
            }
            hex_text.nodeValue = hex_buf;
            txt_text.nodeValue = txt_buf;
        });
        rd.readAsArrayBuffer(content);

        hex_code.appendChild(hex_text);
        hex_pre.appendChild(hex_code);

        txt_code.appendChild(txt_text);
        txt_pre.appendChild(txt_code);

        return {hex: hex_pre, txt: txt_pre};
    };

    var gen_http_content_div = function(content, content_type) {
        var new_div = document.createElement('div');
        new_div.className = 'stream-content';

        var raw_data = false;
        if (content_type !== null) {
            content_type = content_type.toLowerCase();
            var ct = parse_content_type(content_type);

            if (ct['content_type'].match(/^image\//) !== null) {
                var new_img = document.createElement('img');
                new_div.appendChild(new_img);

                var img_blob = new Blob([content], {'type': ct['content_type']});
                var rd = new FileReader();

                rd.addEventListener('loadend', function() {
                    new_img.src = rd.result;
                });
                rd.readAsDataURL(img_blob);
            } else {
                var hljs_langs = get_langs_by_content_type(ct['content_type']);
                if (hljs_langs !== undefined) {
                    var charset = ct['params']['charset'] ? ct['params']['charset'] : 'utf-8';
                    var new_pre = document.createElement('pre');
                    var new_code = document.createElement('code');
                    var text_blob = new Blob([content], {'type': ct['content_type']});
                    var rd = new FileReader();

                    rd.addEventListener('loadend', function() {
                        var result = rd.result;
                        if (ct['content_type'].match(/json/) !== null) {
                            try {
                                result = format_json(JSON.parse(result));
                            } catch (err) {
                                result = rd.result;
                            }
                        }
                        set_text(new_code, result);

                        var new_code_obj = $(new_code);
                        new_code_obj.data('content_need_hl', 'true');
                        new_code_obj.data('content_type', ct['content_type']);
                    });

                    new_pre.appendChild(new_code);
                    new_div.appendChild(new_pre);

                    rd.readAsText(text_blob, charset);
                } else {
                    raw_data = true;
                }
            }
        } else {
            raw_data = true;
        }

        if (raw_data) {
            var new_pres = gen_raw_data_pre_code(content);
            new_div.appendChild(new_pres.hex);
            new_div.appendChild(new_pres.txt);
        }

        return new_div;
    };

    var gen_raw_data_list = function (stream, raw_data) {
        var ul, li, new_div;

        new_div = document.createElement('div');
        new_div.className = 'stream-content';
        ul = document.createElement('ul');
        li = document.createElement('li');
        li.className = get_li_class_by_idx(0);
        var new_pres = gen_raw_data_pre_code(raw_data);
        new_div.appendChild(new_pres.hex);
        new_div.appendChild(new_pres.txt);
        li.appendChild(new_div);
        ul.appendChild(li);

        return ul;
    };

    var gen_http_rep_list = function(stream) {
        var ul, li, sub_header, sub_ul, sub_li;
        var li_idx = 0;

        ul = document.createElement('ul');

        li = gen_detail_li('Status', stream['status'] + ' ' + stream['status_str'], li_idx++);
        ul.appendChild(li);

        li = gen_detail_li('HTTP Version', stream['version'], li_idx++);
        ul.appendChild(li);

        li = document.createElement('li');
        li.className = get_li_class_by_idx(0);
        sub_header = gen_detail_header('h2', 'Headers');
        li.appendChild(sub_header);

        sub_ul = document.createElement('ul');
        var hname, hval, content_type = null;
        for (var h = 0; h < stream['headers'].length; h++) {
            hname = stream['headers'][h][0];
            hval = stream['headers'][h][1];
            sub_li = gen_detail_li(hname, hval, h);
            sub_ul.appendChild(sub_li);

            if (hname === 'CONTENT-TYPE') {
                content_type = hval;
            }
        }
        li.appendChild(sub_ul);
        ul.appendChild(li);

        if (stream['content'].size > 0) {
            li = document.createElement('li');
            li.className = get_li_class_by_idx(0);
            sub_header = gen_detail_header('h2', 'Content');
            li.appendChild(sub_header);
            var content_div = gen_http_content_div(stream['content'], content_type);
            li.appendChild(content_div);
            ul.appendChild(li);
        }

        return ul;
    };

    var gen_http_req_list = function(stream) {
        var ul, li, sub_header, sub_ul, sub_li;
        var li_idx = 0;

        ul = document.createElement('ul');

        li = gen_detail_li('Method', stream['method'], li_idx++);
        ul.appendChild(li);

        var split_path, path, qs;
        split_path = stream['path'].split('?');
        path = split_path[0];
        qs = split_path.slice(1).join('?');

        li = gen_detail_li('Path', path, li_idx++);
        ul.appendChild(li);

        if (qs.length > 0) {
            li = gen_detail_li('Query String', qs, li_idx++);
            ul.appendChild(li);
        }

        li = gen_detail_li('HTTP Version', stream['version'], li_idx++);
        ul.appendChild(li);

        li = document.createElement('li');
        li.className = get_li_class_by_idx(0);
        sub_header = gen_detail_header('h2', 'Headers');
        li.appendChild(sub_header);

        sub_ul = document.createElement('ul');
        var hname, hval, content_type = null;
        for (var h = 0; h < stream['headers'].length; h++) {
            hname = stream['headers'][h][0];
            hval = stream['headers'][h][1];
            sub_li = gen_detail_li(hname, hval, h);
            sub_ul.appendChild(sub_li);

            if (hname === 'CONTENT-TYPE') {
                content_type = hval;
            }
        }
        li.appendChild(sub_ul);
        ul.appendChild(li);

        if (stream['content'].size > 0) {
            li = document.createElement('li');
            li.className = get_li_class_by_idx(0);
            sub_header = gen_detail_header('h2', 'Content');
            li.appendChild(sub_header);
            var content_div = gen_http_content_div(stream['content'], content_type);
            li.appendChild(content_div);
            ul.appendChild(li);
        }

        return ul;
    };

    var pin_flow = function (flow) {
        if (flow !== undefined) {
            flow.pinned = true;
        }
    };

    var unpin_flow = function (flow) {
        if (flow !== undefined) {
            delete flow.pinned;
        }
    };

    var lookup_flow_by_stream = function (stream, create) {
        var flow_id;
        var server;
        var client;

        if (stream['type'] === 'http-req') {
            server = enclose_addr(stream['dst_addr']) + ':' + stream['dst_port'];
            client = enclose_addr(stream['src_addr']) + ':' + stream['src_port'];
            flow_id = server + '-' + client;
        } else {
            if (stream['type'] === 'http-rep') {
                server = enclose_addr(stream['src_addr']) + ':' + stream['src_port'];
                client = enclose_addr(stream['dst_addr']) + ':' + stream['dst_port'];
                flow_id = server + '-' + client;
            } else {
                server = enclose_addr(stream['src_addr']) + ':' + stream['src_port'];
                client = enclose_addr(stream['dst_addr']) + ':' + stream['dst_port'];
                flow_id = null;
            }
        }

        if (flow_id !== null) {
            if (flows[flow_id] === undefined && create === true) {
                flows[flow_id] = new Array();
            }
            return flows[flow_id];
        } else {
            var id1 = server + '-' + client;
            var id2 = client + '-' + server;

            if (flows[id1] !== undefined) {
                return flows[id1];
            } else {
                if (flows[id2] !== undefined) {
                    return flows[id2];
                } else {
                    if (create === true) {
                        flows[id2] = new Array();
                    }
                    return flows[id2]
                }
            }
        }
    };

    var gen_log_detail = function (stream, raw_data) {
        var body_div = document.createElement('div');
        body_div.className = 'event-detail';

        body_div.appendChild(gen_detail_header('h1', 'Network'));
        body_div.appendChild(gen_network_list(stream));

        if (stream['type'] === 'http-req') {
            body_div.appendChild(gen_detail_header('h1', 'HTTP Request'));
            body_div.appendChild(gen_http_req_list(stream));
        } else {
            if (stream['type'] === 'http-rep') {
                body_div.appendChild(gen_detail_header('h1', 'HTTP Response'));
                body_div.appendChild(gen_http_rep_list(stream));
            } else {
                body_div.appendChild(gen_detail_header('h1', 'Raw Data'));
                body_div.appendChild(gen_raw_data_list(stream, raw_data));
            }
        }

        return body_div;
    };

    var log_event = function (content) {
        var stream = content['stream'];
        var brief_desc;
        var content_class;

        if (stream !== undefined) {
            if (stream['type'] === 'http-req') {
                brief_desc = stream['request_line'];
                content_class = 'http-request';
            } else {
                if (stream['type'] === 'http-rep') {
                    brief_desc = stream['status_line'];
                    var first_status = stream['status'].slice(0, 1);
                    if (first_status === '2') {
                        content_class = 'http-reply status-2xx';
                    } else {
                        if (first_status === '3') {
                            content_class = 'http-reply status-3xx';
                        } else {
                            if (first_status === '4') {
                                content_class = 'http-reply status-4xx';
                            } else {
                                if (first_status === '5') {
                                    content_class = 'http-reply status-5xx';
                                } else {
                                    content_class = 'http-reply';
                                }
                            }
                        }
                    }
                } else {
                    brief_desc = 'Raw Data';
                    content_class = 'raw-data';
                }
            }
        } else {
            brief_desc = content['brief_desc'];
            content_class = content['class'];
        }

        var newd = document.createElement('div');
        var timed = document.createElement('div');
        var new_ev_content = document.createElement('div');
        var now = new Date();
        var side_buttons, side_buttons_obj;

        new_ev_content.appendChild(document.createTextNode(brief_desc));
        new_ev_content.className = 'event-content ' + content_class;
        timed.appendChild(document.createTextNode((now - start_time)/1000));
        timed.className = 'event-time';
        newd.className = 'event-list-item';
        newd.appendChild(timed);
        newd.appendChild(new_ev_content);

        if (stream !== undefined) {
            side_buttons = document.createElement('div');
            side_buttons.className = 'side-buttons';
            newd.appendChild(side_buttons);
            side_buttons_obj = $(side_buttons);

            var pin_button = document.createElement('i');
            pin_button.className = 'fa fa-thumb-tack side-button pin-button';
            pin_button_obj = $(pin_button);
            pin_button_obj.click(function(ev) {
                ev.stopPropagation();

                var flow = lookup_flow_by_stream(stream, false);

                if (flow !== undefined) {
                    if (flow.pinned === true) {
                        unpin_flow(flow);
                        for (var i = 0; i < flow.length; i++) {
                            $(flow[i].getElementsByClassName('pin-button')[0]).removeClass('down');
                        }
                    } else {
                        pin_flow(flow);
                        for (var i = 0; i < flow.length; i++) {
                            $(flow[i].getElementsByClassName('pin-button')[0]).addClass('down');
                        }
                    }
                }
            });

            var flow_button_down = document.createElement('i');
            flow_button_down.className = 'fa fa-chevron-down side-button flow-button-down';
            var flow_button_down_obj = $(flow_button_down);
            flow_button_down_obj.click(function (ev) {
                ev.stopPropagation();

                var mouse_y = ev.clientY;
                var cur_y = $(newd).position().top;

                var flow = lookup_flow_by_stream(stream, false);
                for (var s = 0; s < flow.length; s++) {
                    if (flow[s] === newd && (s + 1) < flow.length) {
                        var next_obj = $(flow[s + 1]);
                        var next_y = next_obj.position().top;

                        if (next_obj.data('detail_shown') !== true) {
                            next_obj.click();
                        }
                        window.scrollTo(0, cur_y - mouse_y + (next_y - cur_y) + next_obj.height() / 2);
                        break;
                    }
                }
            });

            var flow_button_up = document.createElement('i');
            flow_button_up.className = 'fa fa-chevron-up side-button flow-button-up';
            var flow_button_up_obj = $(flow_button_up);
            flow_button_up_obj.click(function (ev) {
                ev.stopPropagation();

                var mouse_y = ev.clientY;
                var cur_y = $(newd).position().top;

                var flow = lookup_flow_by_stream(stream, false);
                for (var s = 0; s < flow.length; s++) {
                    if (flow[s] === newd && (s - 1) >= 0) {
                        var prev_obj = $(flow[s - 1]);
                        var prev_y = prev_obj.position().top;

                        if (prev_obj.data('detail_shown') !== true) {
                            prev_obj.click();
                        }
                        window.scrollTo(0, cur_y - mouse_y - (cur_y - prev_y) + prev_obj.height() / 2);
                        break;
                    }
                }
            });

            side_buttons.appendChild(flow_button_up);
            side_buttons.appendChild(flow_button_down);
            side_buttons.appendChild(pin_button);
        }

        log_target.appendChild(newd);


        if (stream !== undefined) {
            var log_detail = gen_log_detail(stream, content['raw_data']);
            log_target.appendChild(log_detail);

            var mouseenter_handler = function () {
                side_buttons_obj.show();

                var flow = lookup_flow_by_stream(stream, false);
                if (flow === undefined) {
                    return;
                }

                for (var i = 0; i < flow.length; i++) {
                    $(flow[i].getElementsByClassName('event-content')[0]).addClass('highlighted');
                }
            };

            var mouseleave_handler = function () {
                side_buttons_obj.hide();

                var flow = lookup_flow_by_stream(stream, false);
                if (flow === undefined) {
                    return;
                }

                if (flow.pinned === true) {
                    return;
                }

                for (var i = 0; i < flow.length; i++) {
                    $(flow[i].getElementsByClassName('event-content')[0]).removeClass('highlighted');
                }
            };

            var newd_obj = $(newd);

            newd_obj.mouseenter(mouseenter_handler);

            newd_obj.mouseleave(mouseleave_handler);

            newd_obj.click(function (ev) {
                ev.stopPropagation();

                var detail_obj = $(log_detail);
                detail_obj.toggle();

                if (detail_obj.css('display') === 'none') {
                    newd_obj.data('detail_shown', 'false');
                } else {
                    newd_obj.data('detail_shown', 'true');
                }

                if (detail_obj.css('display') !== 'none') {
                    var code_list = log_detail.getElementsByTagName('code');

                    var code_obj, code_ct, hljs_langs;
                    for (var c = 0; c < code_list.length; c++) {
                        code_obj = $(code_list[c]);
                        if (code_obj.data('highlighted') === undefined
                                && code_obj.data('content_need_hl') === true) {
                            code_obj.data('highlighted', 'true');

                            code_ct = code_obj.data('content_type');
                            hljs_langs = get_langs_by_content_type(code_ct);
                            if (hljs_langs === undefined) {
                                hljs.configure({languages: hljs.listLanguages()});
                            } else {
                                hljs.configure({languages: hljs_langs});
                            }
                            hljs.highlightBlock(code_list[c]);
                        }
                    }
                }
            });
        }

        if (following_events === true) {
            auto_scrolling = true;
            newd.scrollIntoView(true);
        }

        return newd;
    };

    var get_ws_addr = function () {
        var loc = window.location;
        var ws_uri;

        if (loc.protocol === 'https:') {
            ws_uri = 'wss://';
        } else {
            ws_uri = 'ws://';
        }
        if (loc.pathname[loc.pathname.length - 1] !== '/') {
            ws_uri += (loc.host + loc.pathname + '/ws');
        } else {
            ws_uri += (loc.host + loc.pathname + 'ws');
        }

        return ws_uri;
    };

    var append_to_flow = function (stream, ev_item) {
        var flow = lookup_flow_by_stream(stream, true);
        flow.push(ev_item);
    };

    var parse_headers = function(msg) {
        header_end = msg.indexOf('\r\n\r\n');
        if (header_end >= 0) {
            var header_len = header_end + '\r\n\r\n'.length;
            var headers = msg.slice(0, header_len);
            var content = msg.slice(header_len);

            headers = headers.split('\r\n');

            var headers_arr = new Array();

            for (var h = 0; h < headers.length; h++) {
                if (headers[h].length <= 0) {
                    continue;
                }

                hs = headers[h].split(':');
                hname = hs[0].trim();
                hval = hs.slice(1).join(':').trim();
                headers_arr.push([hname, hval]);
            }

            var content_blob = new Blob([binary_string_to_arraybuffer(content)]);

            return {'headers': headers_arr, 'content': content_blob};
        } else {
            return null;
        }
    }

    var parse_msg = function(msg) {
        var topic_match = msg.match(topic_re);

        if (topic_match === null) {
            console.log(topic_match);
            return null;
        }

        var topic = topic_match[0];

        var complete = false;

        msg = msg.slice(topic.length);

        if (msg.length > 0) {
            if (streams[topic] === undefined) {  // New stream, need to parse the headers
                var src_addr = topic_match[2] ? topic_match[2] : topic_match[4];
                var src_port = topic_match[5];
                var dst_addr = topic_match[7] ? topic_match[7] : topic_match[9];
                var dst_port = topic_match[10];

                req_match = msg.match(http_req_re);

                if (req_match !== null) {
                    // HTTP request
                    var req_line = req_match[0];

                    msg = msg.slice(req_line.length);
                    var headers_and_content = parse_headers(msg);
                    if (headers_and_content !== null) {
                        streams[topic] = {
                            'type': 'http-req',
                            'topic': topic,
                            'src_addr': src_addr,
                            'src_port': src_port,
                            'dst_addr': dst_addr,
                            'dst_port': dst_port,
                            'request_line': req_line,
                            'method': req_match[1],
                            'path': req_match[2],
                            'version': req_match[3],
                            'headers': headers_and_content['headers'],
                            'content': headers_and_content['content']
                        };
                    }
                } else {
                    rep_match = msg.match(http_rep_re);

                    if (rep_match !== null) {
                        // HTTP response
                        var rep_line = rep_match[0];

                        msg = msg.slice(rep_line.length);
                        var headers_and_content = parse_headers(msg);
                        if (headers_and_content !== null) {
                            streams[topic] = {
                                'type': 'http-rep',
                                'topic': topic,
                                'src_addr': src_addr,
                                'src_port': src_port,
                                'dst_addr': dst_addr,
                                'dst_port': dst_port,
                                'status_line': rep_line,
                                'status': rep_match[2],
                                'status_str': rep_match[3],
                                'version': rep_match[1],
                                'headers': headers_and_content['headers'],
                                'content': headers_and_content['content']
                            };
                        }
                    } else {
                        // Raw data
                        streams[topic] = {
                            'type': 'raw',
                            'topic': topic,
                            'src_addr': src_addr,
                            'src_port': src_port,
                            'dst_addr': dst_addr,
                            'dst_port': dst_port,
                        };
                        complete = true;
                    }
                }
            } else {    // Old stream
                var stream_type = streams[topic]['type'];
                if (stream_type === 'http-req' || stream_type === 'http-rep') {
                    streams[topic]['content'] = new Blob([streams[topic]['content'], binary_string_to_arraybuffer(msg)]);
                } else {
                    complete = true;
                }
            }
        } else {    // EOF received
            if (streams[topic] !== undefined) {
                var stream_type = streams[topic]['type'];
                if (stream_type === 'http-req' || stream_type === 'http-rep') {
                    complete = true;
                }
            }
        }

        return {'topic': topic, 'complete': complete};
    }

    var init_ws_conn = function (conn) {
        conn.onopen = function() {
            log_event({
                'class': 'local-msg',
                'brief_desc': 'Connected.'
            });

            $.ajax({
                type: 'GET',
                url:  'proxy.json',
                success: function(data) {
                    var proxy_host = data.http_proxies[0].host;
                    var proxy_port = data.http_proxies[0].port;
                    log_event({
                        'class': 'local-msg',
                        'brief_desc': 'HTTP proxy running at ' 
                            + proxy_host + ':' + proxy_port
                    });
                },
                error: function (xhr, type) {
                    log_event({
                        'class': 'local-msg',
                        'brief_desc': 'Failed to locate the proxy server.'
                    });
                }
            });
        };

        conn.onmessage = function(e) {
            var rd = new FileReader();
            rd.addEventListener('loadend', function() {
                var msg = rd.result;
                var parsed_msg = parse_msg(msg);

                if (parsed_msg === null) {
                    // ignore illegal messages
                    console.log(msg);
                    return;
                }

                if (parsed_msg['complete']) {
                    var s = streams[parsed_msg['topic']];
                    var src_addr = enclose_addr(s['src_addr']);
                    var dst_addr = enclose_addr(s['dst_addr']);
                    var src_addr_port = src_addr + ':' + s['src_port'];
                    var dst_addr_port = dst_addr + ':' + s['dst_port'];

                    var subs_match = false;
                    for (var c in subscriptions) {
                        if (subscriptions[c].type === 'trigger') {
                            if (src_addr === subscriptions[c].ep1
                                    || dst_addr === subscriptions[c].ep1
                                    || src_addr_port === subscriptions[c].ep1
                                    || dst_addr_port === subscriptions[c].ep1) {
                                subs_match = true;
                                break;
                            }
                        } else {    // subscriptions[c].type === subscribe
                            var cases_to_test = [
                                [src_addr, dst_addr],
                                [dst_addr, src_addr],
                                [src_addr_port, dst_addr],
                                [dst_addr, src_addr_port],
                                [src_addr, dst_addr_port],
                                [dst_addr_port, src_addr],
                                [src_addr_port, dst_addr_port],
                                [dst_addr_port, src_addr_port]
                            ];
                            for (var i = 0; i < cases_to_test.length; i ++) {
                                if (cases_to_test[i][0] === subscriptions[c].ep1
                                        && cases_to_test[i][1] === subscriptions[c].ep2) {
                                    subs_match = true;
                                    break;
                                }
                            }
                            if (subs_match === true) {
                                break;
                            }
                        }
                    }

                    if (subs_match) {
                        var ev_item;

                        if (s['type'] === 'http-req') {
                            ev_item = log_event({
                                'stream': s
                            });
                        } else {
                            if (s['type'] === 'http-rep') {
                                ev_item = log_event({
                                    'stream': s
                                });
                            } else {
                                var raw_msg = msg.slice(s.topic.length);
                                ev_item = log_event({
                                    'stream': s,
                                    'raw_data': new Blob([binary_string_to_arraybuffer(raw_msg)])
                                });
                            }
                        }

                        append_to_flow(s, ev_item);

                        delete streams[parsed_msg['topic']];
                    }
                }
            });
            rd.readAsBinaryString(e.data);
        };

        conn.onerror = function(e) {
            console.log(e);
        };

        conn.onclose = function(e) {
            log_event({
                'class': 'local-msg',
                'brief_desc': 'Disconnected, code = ' + e.code + ', reason = ' + e.reason
            });
        };

        ws_conn = conn;
    };

    var init_ui = function () {
        var subs_panel_obj = $('#subscribe-panel');
        var subs_button_obj = $('#subscribe-button');
        var ep1_obj = $('#endpoint1');
        var ep2_obj = $('#endpoint2');
        var subs_submit_button_obj = $('#subs-submit-button');
        $('#subscribe-panel > .panel-title > .close-button').click(function () {
            subs_button_obj.click();
        });
        $('#subscribe-panel > input[type="text"]').focus(function () {
            this.select();
        });
        subs_button_obj.click(function () {
            if (subs_panel_obj.css('display') !== 'none') {
                subs_panel_obj.hide();
                subs_button_obj.removeClass('down');
            } else {
                $('.toolbar-panel').hide();
                $('#cmd-list > li').removeClass('down');

                subs_panel_obj.show();
                subs_button_obj.addClass('down');
                ep1_obj.focus();
            }
        });
        var check_endpoint_addr = function (addr) {
            if (addr.match(endpoint4_re) === null) {
                var ep6_ip_match = addr.match(endpoint6_ip_only_re);
                if (ep6_ip_match === null) {
                    var ep6_ip_port_match = addr.match(endpoint6_ip_port_re);
                    if (ep6_ip_port_match === null) {
                        return null;
                    } else {
                        var segs = (ep6_ip_port_match[1] + ep6_ip_port_match[4]).split(':');
                        if (ep6_ip_port_match[3] === ':' && segs.length > 7) {
                            return null;
                        }
                        if (ep6_ip_port_match[3] === '' && segs.length !== 8) {
                            return null;
                        }
                        return 'ipv6_ip_port';
                    }
                } else {
                    var segs = (ep6_ip_match[1] + ep6_ip_match[4]).split(':');
                    if (ep6_ip_match[3] === ':' && segs.length > 7) {
                        return null;
                    }
                    if (ep6_ip_match[3] === '' && segs.length != 8) {
                        return null;
                    }
                    return 'ipv6_ip_only';
                }
            } else {
                return 'ipv4';
            }
        };
        var ep_input_checker = function (ev) {
            ev.stopPropagation();
            var jq_obj = $(this);
            var val = jq_obj.val();
            var input_type = check_endpoint_addr(val);

            if (val.length <= 0 || input_type !== null) {
                jq_obj.removeClass('error');
            } else {
                jq_obj.addClass('error');
            }
        };
        var ep_keypress = function(ev) {
            ev.stopPropagation();
            if (ev.keyCode === 13 || ev.keyCode === 10) {   // Enter
                subs_submit_button_obj.click();
            }
        };
        ep1_obj.on('input', ep_input_checker);
        ep2_obj.on('input', ep_input_checker);
        ep1_obj.keypress(ep_keypress);
        ep2_obj.keypress(ep_keypress);
        var normalize_ep_val = function (val, val_type) {
            if (val_type === 'ipv6_ip_only') {
                return '[' + val + ']'
            }
            return val;
        };
        subs_submit_button_obj.click(function (ev) {
            ev.stopPropagation();

            var val1 = ep1_obj.val().trim();
            var val2 = ep2_obj.val().trim();
            var val1_type = check_endpoint_addr(val1);
            var val2_type = check_endpoint_addr(val2);
            var subs_msg_content = $('#subscribe-message-content');
            var subs_msg = $('#subscribe-panel > .subscribe-message');
            var subs_cmd, subs_cmd_alt;
            var subs_obj;

            if (val1_type !== null && val2_type !== null) {
                val1 = normalize_ep_val(val1, val1_type);
                val2 = normalize_ep_val(val2, val2_type);

                subs_cmd = 'subscribe ' + val1 + ' ' + val2;
                subs_cmd_alt = 'subscribe ' + val2 + ' ' + val1;
                if (subscriptions[subs_cmd] !== undefined 
                        || subscriptions[subs_cmd_alt] !== undefined) {
                    subs_button_obj.click();
                    subs_msg.hide();
                    return;
                }
                subs_obj = {
                    'type': 'subscribe',
                    'ep1': val1,
                    'ep2': val2
                };
                subscriptions[subs_cmd] = subs_obj;

                ws_conn.send(subs_cmd);
                subs_button_obj.click();
                subs_msg.hide();
                return;
            }

            if (val1_type !== null && val2_type === null && val2.length === 0) {
                val1 = normalize_ep_val(val1, val1_type);

                subs_cmd = 'trigger ' + val1;
                if (subscriptions[subs_cmd] !== undefined) {
                    subs_button_obj.click();
                    subs_msg.hide();
                    return;
                }
                subs_obj = {
                    'type': 'trigger',
                    'ep1': val1,
                };
                subscriptions[subs_cmd] = subs_obj;

                ws_conn.send(subs_cmd);
                subs_button_obj.click();
                subs_msg.hide();
                return;
            }

            if (val2_type !== null && val1_type === null && val1.length === 0) {
                val2 = normalize_ep_val(val2, val2_type);

                subs_cmd = 'trigger ' + val2;
                if (subscriptions[subs_cmd] !== undefined) {
                    subs_button_obj.click();
                    subs_msg.hide();
                    return;
                }
                subs_obj = {
                    'type': 'trigger',
                    'ep1': val2,
                };
                subscriptions[subs_cmd] = subs_obj;

                ws_conn.send(subs_cmd);
                subs_button_obj.click();
                subs_msg.hide();
                return;
            }

            if (val1.length === 0 && val2.length === 0) {
                subs_msg_content.html('All endpoints are empty');
                subs_msg.show();
                return;
            }

            subs_msg_content.html('Illegal endpoint specification');
            subs_msg.show();
        });

        var subs_list_button_obj = $('#subscription-list-button');
        var subs_list_panel_obj = $('#subs-list-panel');
        $('#subs-list-panel > .panel-title > .close-button').click(function () {
            subs_list_button_obj.click();
        });
        subs_list_button_obj.click(function () {
            if (subs_list_panel_obj.css('display') !== 'none') {
                subs_list_panel_obj.hide();
                subs_list_button_obj.removeClass('down');
            } else {
                $('.toolbar-panel').hide();
                $('#cmd-list > li').removeClass('down');

                $('.subs-list-item').remove();
                var item, item_obj, display_text;
                for (var c in subscriptions) {
                    item = document.createElement('span');
                    item.className = 'subs-list-item';
                    if (subscriptions[c].type === 'trigger') {
                        display_text = subscriptions[c].ep1;
                    } else {
                        display_text = subscriptions[c].ep1 + ' - ' + subscriptions[c].ep2;
                    }
                    set_text(item, display_text);
                    item.title = 'Unsubscribe';
                    item_obj = $(item);
                    item_obj.data('subs_cmd_name', c);
                    item_obj.click(function () {
                        var this_obj = $(this);
                        var subs_cmd = this_obj.data('subs_cmd_name');
                        var subs_ep_arr = subs_cmd.split(' ').slice(1);
                        ws_conn.send('unsubscribe ' + subs_ep_arr.join(' '));
                        this_obj.remove();
                        delete subscriptions[subs_cmd];
                    });
                    subs_list_panel_obj[0].appendChild(item);
                }
                subs_list_panel_obj.show();
                subs_list_button_obj.addClass('down');
            }
        });

        var search_button_obj = $('#search-button');
        var search_input_obj = $('#search-input');
        var search_text_obj = $('#search-text');
        /* TODO */
        //search_button_obj.click(function () {
        //    if (search_input_obj.css('display') !== 'none') {
        //        search_input_obj.hide();
        //        search_button_obj.removeClass('down');
        //    } else {
        //        search_input_obj.show();
        //        search_button_obj.addClass('down');
        //        search_text_obj.focus();
        //    }
        //});
        search_text_obj.keypress(function(ev) {
            // TODO
            console.log(ev);
            if (ev.keyCode === 13 || ev.keyCode === 10) {   // Enter
                console.log('Enter pressed');
            }
        });
        search_text_obj.focus(function () {
            this.select();
        });

        var clear_log_button_obj = $('#clear-log-button');
        clear_log_button_obj.click(function () {
            flows = {};
            log_target.innerHTML = '';
            log_event({
                'class': 'local-msg',
                'brief_desc': 'Logs cleared.'
            });
        });

        var reconnect_button_obj = $('#re-connect-button');
        reconnect_button_obj.click(function () {
            if (ws_conn !== undefined) {
                ws_conn.onclose = undefined;
                ws_conn.close();

                subscriptions = {};

                var ws_uri = get_ws_addr();
                var conn = new WebSocket(ws_uri);
                log_event({
                    'class': 'local-msg',
                    'brief_desc': 'Re-connecting to Shinpachi....'
                });
                init_ws_conn(conn);
            }
        });

        var open_all_button_obj = $('#open-all-button');
        open_all_button_obj.click(function () {
            $('#event-list > .event-detail').hide();
            $('#event-list > .event-list-item').each(function (idx, elem) {
                $(elem).click();
            });
        });

        var close_all_button_obj = $('#close-all-button');
        close_all_button_obj.click(function () {
            $('#event-list > .event-detail').hide();
            $('#event-list > .event-list-item').data('detail_shown', 'false');
        });

        var follow_event_button_obj = $('#follow-event-button');
        follow_event_button_obj.click(function () {
            if (follow_event_button_obj.hasClass('down')) {
                following_events = false;
                follow_event_button_obj.removeClass('down');
            } else {
                following_events = true;
                follow_event_button_obj.addClass('down');

                auto_scrolling = true;
                $('#event-list > .event-list-item').last()[0].scrollIntoView(true);
            }
        });
        $(window).scroll(function (ev) {
            if (auto_scrolling === true) {
                auto_scrolling = false;
                return;
            }

            if (follow_event_button_obj.hasClass('down')) {
                follow_event_button_obj.click();
            }
        });

        var charcode_to_action = {
            // 's', subscribe
            83:     function() { subs_button_obj.click(); },
            115:    function() { subs_button_obj.click(); },

            // 'l', subscription list
            76:     function() { subs_list_button_obj.click(); },
            108:    function() { subs_list_button_obj.click(); },

            // '/', search
            47:     function() { search_button_obj.click(); },

            // 'c', clear log
            67:     function() { clear_log_button_obj.click(); },
            99:     function() { clear_log_button_obj.click(); },

            // 'r', re-connect
            82:     function() { reconnect_button_obj.click(); },
            114:    function() { reconnect_button_obj.click(); },

            // '+', open all
            43:     function() { open_all_button_obj.click(); },

            // '-', close all
            45:     function() { close_all_button_obj.click(); },

            // 'f', follow events
            70:     function() { follow_event_button_obj.click(); },
            102:    function() { follow_event_button_obj.click(); }
        };
        $('body').keypress(function (ev) {
            if (ev.ctrlKey || ev.altKey) {
                return;
            }

            var action = charcode_to_action[ev.charCode];
            if (action !== undefined) {
                ev.preventDefault();
                action();
            }
        });
    };

    var init_console = function () {
        log_target = document.getElementById('event-list');

        var ws_uri = get_ws_addr();
        var conn = new WebSocket(ws_uri);
        start_time = new Date();
        log_event({
            'class': 'local-msg',
            'brief_desc': 'Connecting to Shinpachi....'
        });

        init_ui();

        init_ws_conn(conn);
    };

    $(init_console);
})(Zepto);
