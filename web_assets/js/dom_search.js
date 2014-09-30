(function (doc, win) {
    var Searcher = function (dom_elem) {
        this.dom_element = dom_elem;

        this.search = function (pattern) {
            var re;
            if (pattern.constructor === RegExp) {
                re = pattern;
            } else {
                if (pattern.constructor === String) {
                    re = new RegExp(pattern, 'i');
                }
            }

            if (re === undefined) {
                return null;
            }

            var next_node = function (cur_node) {
                if (cur_node.childNodes.length === 0) {
                    if (cur_node.nextSibling === null) {
                        var n_node = cur_node.parentNode;
                        while (n_node !== searcher.dom_element && n_node.nextSibling === null) {
                            n_node = n_node.parentNode;
                        }
                        if (n_node === searcher.dom_element) {
                            return null;
                        } else {
                            return n_node.nextSibling;
                        }
                    } else {
                        return cur_node.nextSibling;
                    }
                } else {
                    return cur_node.childNodes[0];
                }
            };

            var cur_node = this.dom_element;
            var prev_idx = 0;
            var searcher = this;

            var match_next_node = function () {
                var m = null;
                var switch_node = true;
                var old_idx = prev_idx;

                prev_idx = 0;

                if (cur_node.nodeType === doc.TEXT_NODE) {
                    m = cur_node.nodeValue.slice(old_idx).match(re);
                    if (m !== null) {
                        next_idx = m.index + old_idx + m[0].length;
                        if (next_idx < cur_node.nodeValue.length) {
                            switch_node = false;
                            prev_idx = next_idx;
                        }
                    }
                }

                var ret;
                if (m === null) {
                    ret = null;
                } else {
                    m.index = m.index + old_idx;
                    ret = {'elem': cur_node, 'match': m};
                }

                if (switch_node) {
                    cur_node = next_node(cur_node);
                }

                return ret;
            };

            var next_func = function () {
                var r = null;
                while (cur_node !== null) {
                    r = match_next_node();
                    if (r !== null) {
                        break;
                    }
                }

                return r;
            };

            return next_func;
        };
    };

    win.Searcher = Searcher;
})(document, window);
