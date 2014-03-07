#
# A collection of shared functions for managing help flag mapping files.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#

import importlib
import os
import re
import sys

import git
import stevedore
import xml.sax.saxutils

import openstack.common.config.generator as generator
from oslo.config import cfg


# gettext internationalisation function requisite:
import __builtin__
__builtin__.__dict__['_'] = lambda x: x


def git_check(repo_path):
    """Check a passed directory to verify it is a valid git repository."""

    try:
        repo = git.Repo(repo_path)
        assert repo.bare is False
        package_name = os.path.basename(repo.remotes.origin.url).rstrip('.git')
    except Exception:
        print("\nThere is a problem verifying that the directory passed in")
        print("is a valid git repository.  Please try again.\n")
        sys.exit(1)
    return package_name


def import_modules(repo_location, package_name, verbose=0):
    """Import modules.

    Loops through the repository, importing module by module to
    populate the configuration object (cfg.CONF) created from Oslo.
    """
    modules = {}
    pkg_location = os.path.join(repo_location, package_name)
    for root, dirs, files in os.walk(pkg_location):
        skipdir = False
        for excludedir in ('tests', 'locale', 'cmd',
                           os.path.join('db', 'migration'), 'transfer'):
            if ((os.path.sep + excludedir + os.path.sep) in root or (
                    root.endswith(os.path.sep + excludedir))):
                skipdir = True
                break
        if skipdir:
            continue
        for pyfile in files:
            if pyfile.endswith('.py'):
                modfile = os.path.join(root, pyfile).split(repo_location, 1)[1]
                modname = os.path.splitext(modfile)[0].split(os.path.sep)
                modname = [m for m in modname if m != '']
                modname = '.'.join(modname)
                if modname.endswith('.__init__'):
                    modname = modname[:modname.rfind(".")]
                try:
                    module = importlib.import_module(modname)
                    modules[modname] = module
                    if verbose >= 1:
                        print("imported %s" % modname)
                except ImportError as e:
                    """
                    work around modules that don't like being imported in
                    this way FIXME This could probably be better, but does
                    not affect the configuration options found at this stage
                    """
                    if verbose >= 2:
                        print("Failed to import: %s (%s)" % (modname, e))
                    continue
                except cfg.DuplicateOptError as e:
                    """
                    oslo.cfg doesn't allow redefinition of a config option, but
                    we don't mind. Don't fail if this happens.
                    """
                    if verbose >= 2:
                        print(e)
                    continue
    return modules


class OptionsCache(object):
    def __init__(self, modules, verbose=0):
        self._verbose = verbose
        self._opts_by_name = {}
        self._opt_names = []

        for optname in cfg.CONF._opts:
            self._add_opt(optname, 'DEFAULT', cfg.CONF._opts[optname]['opt'])

        for group in cfg.CONF._groups:
            for optname in cfg.CONF._groups[group]._opts:
                self._add_opt(group + '/' + optname, group,
                              cfg.CONF._groups[group]._opts[optname]['opt'])

        self._opt_names.sort(OptionsCache._cmpopts)

    def _add_opt(self, optname, group, opt):
        if optname in self._opts_by_name:
            if self._verbose >= 2:
                print ("Duplicate option name %s" % optname)
        else:
            self._opts_by_name[optname] = (group, opt)
            self._opt_names.append(optname)

    def __len__(self):
        return len(self._opt_names)

    def load_extension_options(self, module):
        # Note that options loaded this way aren't added to _opts_by_module
        loader = stevedore.named.NamedExtensionManager(
            'oslo.config.opts',
            names=(module,),
            invoke_on_load=False
        )
        for ext in loader:
            for group, opts in ext.plugin():
                for opt in opts:
                    if group is None:
                        self._add_opt(opt.name, 'DEFAULT', opt)
                    else:
                        self._add_opt(group + '/' + opt.name, group, opt)

    def get_option_names(self):
        return self._opt_names

    def get_option(self, name):
        return self._opts_by_name[name]

    @staticmethod
    def _cmpopts(x, y):
        if '/' in x and '/' in y:
            prex = x[:x.find('/')]
            prey = y[:x.find('/')]
            if prex != prey:
                return cmp(prex, prey)
            return cmp(x, y)
        elif '/' in x:
            return 1
        elif '/' in y:
            return -1
        else:
            return cmp(x, y)


def write_docbook(package_name, options, verbose=0, target='./'):
    """Write DocBook tables.

    Prints a docbook-formatted table for every group of options.
    """
    options_by_cat = {}

    # Compute the absolute path of the git repository (the relative path is
    # prepended to sys.path in autohelp.py)
    target_abspath = os.path.abspath(sys.path[0])

    # This regex will be used to sanitize file paths and uris
    uri_re = re.compile(r'(^[^:]+://)?%s' % target_abspath)

    with open(package_name + '.flagmappings') as f:
        for line in f:
            opt, categories = line.split(' ', 1)
            for category in categories.split():
                options_by_cat.setdefault(category, []).append(opt)

    if not os.path.isdir(target):
        os.makedirs(target)

    for cat in options_by_cat.keys():
        file_path = ("%(target)s/%(package_name)s-%(cat)s.xml" %
                     {'target': target, 'package_name': package_name,
                      'cat': cat})
        groups_file = open(file_path, 'w')
        groups_file.write('<?xml version="1.0" encoding="UTF-8"?>\n\
        <!-- Warning: Do not edit this file. It is automatically\n\
             generated and your changes will be overwritten.\n\
             The tool to do so lives in the tools directory of this\n\
             repository -->\n\
        <para xmlns="http://docbook.org/ns/docbook" version="5.0">\n\
        <table rules="all">\n\
          <caption>Description of configuration options for ' + cat +
                          '</caption>\n\
           <col width="50%"/>\n\
           <col width="50%"/>\n\
           <thead>\n\
              <tr>\n\
                  <th>Configuration option = Default value</th>\n\
                  <th>Description</th>\n\
              </tr>\n\
          </thead>\n\
          <tbody>\n')
        curgroup = None
        for optname in options_by_cat[cat]:
            group, option = options.get_option(optname)
            if group != curgroup:
                curgroup = group
                groups_file.write('              <tr>\n')
                groups_file.write('                  ' +
                                  '<th colspan="2">[%s]</th>\n' %
                                  group)
                groups_file.write('              </tr>\n')
            if not option.help:
                option.help = "No help text available for this option"
            if ((type(option).__name__ == "ListOpt") and (
                    option.default is not None)):
                option.default = ", ".join(option.default)
            groups_file.write('              <tr>\n')
            default = generator._sanitize_default(option.name,
                                                  str(option.default))
            # This should be moved to generator._sanitize_default
            # NOTE(gpocentek): The first element in the path is the current
            # project git repository path. It is not useful to test values
            # against it, and it causes trouble if it is the same as the python
            # module name. So we just drop it.
            for pathelm in sys.path[1:]:
                if pathelm == '':
                    continue
                if pathelm.endswith('/'):
                    pathelm = pathelm[:-1]
                if default.startswith(pathelm):
                    default = default.replace(pathelm,
                                              '/usr/lib/python/site-packages')
                    break
            if uri_re.search(default):
                default = default.replace(target_abspath,
                                          '/usr/lib/python/site-packages')
            groups_file.write('                       <td>%s = %s</td>\n' %
                              (option.name, default))
            groups_file.write('                       <td>(%s) %s</td>\n' %
                              (type(option).__name__,
                               xml.sax.saxutils.escape(option.help)))
            groups_file.write('              </tr>\n')
        groups_file.write('       </tbody>\n\
        </table>\n\
        </para>\n')
        groups_file.close()


def create_flagmappings(package_name, options, verbose=0):
    """Create a flagmappings file.

    Create a flagmappings file. This will create a new file called
    $package_name.flagmappings with all the categories set to Unknown.
    """
    with open(package_name + '.flagmappings', 'w') as f:
        for opt in options.get_option_names():
            f.write(opt + ' Unknown\n')


def update_flagmappings(package_name, options, verbose=0):
    """Update flagmappings file.

    Update a flagmappings file, adding or removing entries as needed.
    This will create a new file $package_name.flagmappings.new with
    category information merged from the existing $package_name.flagmappings.
    """
    original_flags = {}
    with open(package_name + '.flagmappings') as f:
        for line in f:
            try:
                flag, category = line.split(' ', 1)
            except ValueError:
                flag = line.strip()
                category = "Unknown"
            original_flags.setdefault(flag, []).append(category.strip())

    updated_flags = []
    for opt in options.get_option_names():
        if len(original_flags.get(opt, [])) == 1:
            updated_flags.append((opt, original_flags[opt][0]))
            continue

        if '/' in opt:
            # Compaitibility hack for old-style flagmappings, where grouped
            # options didn't have their group names prefixed. If there's only
            # one category, we assume there wasn't a conflict, and use it.
            barename = opt[opt.find('/') + 1:]
            if len(original_flags.get(barename, [])) == 1:
                updated_flags.append((opt, original_flags[barename][0]))
                continue

        updated_flags.append((opt, 'Unknown'))

    with open(package_name + '.flagmappings.new', 'w') as f:
        for flag, category in updated_flags:
            f.write(flag + ' ' + category + '\n')

    if verbose >= 1:
        removed_flags = (set(original_flags.keys()) -
                         set([x[0] for x in updated_flags]))
        added_flags = (set([x[0] for x in updated_flags]) -
                       set(original_flags.keys()))

        print("\nRemoved Flags\n")
        for line in sorted(removed_flags, OptionsCache._cmpopts):
            print(line)

        print("\nAdded Flags\n")
        for line in sorted(added_flags, OptionsCache._cmpopts):
            print(line)
