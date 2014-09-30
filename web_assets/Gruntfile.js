
module.exports = function(grunt) {

    grunt.initConfig({

        pkg: grunt.file.readJSON('package.json'),

        concat: {
            options: {
                separator: ';'
            },
            common: {
                src: ['js/shinpachi.js'],
                dest: 'build/common.cat.js'
            },
            console: {
                src: ['js/dom_search.js', 'js/shinpachi_console.js'],
                dest: 'build/console.cat.js'
            }
        },

        uglify: {
            common: {
                options: {
                    banner: '/*! <%= concat.common.src %> <%= grunt.template.today("yyyy-mm-dd") %> */\n'
                },
                src: 'build/common.cat.js',
                dest: 'build/common.min.js'
            },
            console: {
                options: {
                    banner: '/*! <%= concat.console.src %> <%= grunt.template.today("yyyy-mm-dd") %> */\n'
                },
                src: 'build/console.cat.js',
                dest: 'build/console.min.js'
            }
        },

        cssmin: {
            common: {
                options: {
                    banner: '/*! shinpachi_layout.css <%= grunt.template.today("yyyy-mm-dd") %> */\n'
                },
                files: {
                    'build/shinpachi_layout.min.css': ['css/shinpachi_layout.css']
                }
            },
            skeleton: {
                options: {
                    banner: '/*! Compressed Skeleton CSS <%= grunt.template.today("yyyy-mm-dd") %> */\n'
                },
                files: {
                    'build/skeleton.min.css': [
                        'bower_components/skeleton/stylesheets/base.css',
                        'bower_components/skeleton/stylesheets/skeleton.css',
                        'bower_components/skeleton/stylesheets/layout.css'
                    ]
                }
            },
            hljs_theme: {
                options: {
                    banner: '/*! tomorrow.css <%= grunt.template.today("yyyy-mm-dd") %> */\n'
                },
                files: {
                    'build/hljs-theme-tomorrow.min.css': ['lib/highlight.js/src/styles/tomorrow.css']
                }
            }
        },

        shell: {
            build_hljs: {
                command: 'python3 tools/build.py :common',
                options: {
                    stderr: false,
                    execOptions: {
                        cwd: 'lib/highlight.js'
                    }
                }
            }
        },

        copy: {
            debug: {
                files: [
                    {
                        src: 'build/common.cat.js',
                        dest: '../shinpachi/static/js/common.js'
                    },
                    {
                        src: 'build/console.cat.js',
                        dest: '../shinpachi/static/js/console.js'
                    },
                    {
                        src: 'css/shinpachi_layout.css',
                        dest: '../shinpachi/static/css/shinpachi_layout.css'
                    }
                ]
            },
            release: {
                files: [
                    {
                        src: 'build/common.min.js',
                        dest: '../shinpachi/static/js/common.js'
                    },
                    {
                        src: 'build/console.min.js',
                        dest: '../shinpachi/static/js/console.js'
                    },
                    {
                        src: 'bower_components/zepto/zepto.min.js',
                        dest: '../shinpachi/static/js/zepto.min.js'
                    },
                    {
                        src: 'lib/highlight.js/build/highlight.pack.js',
                        dest: '../shinpachi/static/js/highlight.min.js'
                    },
                    {
                        src: 'bower_components/WOW/dist/wow.min.js',
                        dest: '../shinpachi/static/js/wow.min.js'
                    },
                    {
                        src: 'build/hljs-theme-tomorrow.min.css',
                        dest: '../shinpachi/static/css/hljs-theme-tomorrow.min.css'
                    },
                    {
                        src: 'build/shinpachi_layout.min.css',
                        dest: '../shinpachi/static/css/shinpachi_layout.css'
                    },
                    {
                        src: 'build/skeleton.min.css',
                        dest: '../shinpachi/static/css/skeleton.min.css'
                    },
                    {
                        src: 'bower_components/animate.css/animate.min.css',
                        dest: '../shinpachi/static/css/animate.min.css'
                    },
                    {
                        src: 'bower_components/font-awesome/css/font-awesome.min.css',
                        dest: '../shinpachi/static/css/font-awesome.min.css'
                    },
                    {
                        expand: true,
                        cwd: 'bower_components/font-awesome/fonts',
                        src: '**/*',
                        dest: '../shinpachi/static/fonts/'
                    }
                ]
            }
        },

        jshint: {
            files: ['js/**/*.js'],
            options: {
                globals: {
                    jQuery: true,
                    console: true,
                    module: true
                }
            }
        },

        watch: {
            files: ['<%= jshint.files %>'],
            tasks: ['jshint']
        }

    });

    grunt.loadNpmTasks('grunt-contrib-concat');
    grunt.loadNpmTasks('grunt-contrib-uglify');
    grunt.loadNpmTasks('grunt-contrib-cssmin');
    grunt.loadNpmTasks('grunt-contrib-copy');
    grunt.loadNpmTasks('grunt-contrib-jshint');
    grunt.loadNpmTasks('grunt-contrib-watch');
    grunt.loadNpmTasks('grunt-shell');

    grunt.registerTask('default', ['concat', 'uglify', 'cssmin', 'shell']);

};
