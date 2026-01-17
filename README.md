# Kibank-python

Kibank-python is a command line application for listing, extracting and creating bank
files used by [Phase Plant](https://kilohearts.com/products/phase_plant)

This application is a python translation of [kibank](https://github.com/softdevca/kibank) which was developed independently by Sheldon Young.

Kibank-python is *not* Kilohearts product, please do not contact them for support.

## Usage

### Extracting a bank

Extract a bank to a designated directory: extracted

```shell
$ python kibank_extract.py Some.bank -o extracted
```

### Creating a new bank

To create a new bank make a folder next to the script like:
bankfolder/
  index.json
  background.png
  phaseplant/
    Bass/
        ArpBass1.phaseplant
    Leads/
        Leads1.phaseplant

index.json eg.
```json
{
    "id": "author.bankname",
    "author": "author",
    "name": "Bank Name",
    "description": "A great sound bank"
}
```

```shell
$ python kibank_write.py bankfolder bankname.bank
```

## Issues

If you have any problems with or questions about this project, please contact
us through by creating a 
[GitHub issue](https://github.com/suddencreator/kibank-python/issues).

## Contributing

You are invited to contribute to new features, fixes, or updates, large or
small; we are always thrilled to receive pull requests, and do our best to
process them as fast as we can.

Before you start to code, we recommend discussing your plans through a
[GitHub issue](https://github.com/suddencreator/kibank-python/issues), especially for more
ambitious contributions. This gives other
contributors a chance to point you in the right direction, give you feedback on
your design, and help you find out if someone else is working on the same thing.

The copyrights of contributions to this project are retained by their
contributors. No copyright assignment is required to contribute to this
project.

## License

Licensed under the Apache License, Version 2.0 (the "License"); you may not use
this file except in compliance with the License. You may obtain a copy of the 
License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed
under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR 
CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
