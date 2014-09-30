(function () {
    var init_page = function () {
        var login_panel = $("#login-panel");

        $("#login-button").click(function () {
            login_panel.toggle();
        });

        $("#user-info").click(function () {
            login_panel.toggle();
        });

        if ($(".login-message").length > 0) {
            login_panel.show();
        }
    };

    $(init_page);
})();
